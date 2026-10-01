"""专题成果包（可转交复核的定版地层关系封存）。

把某个**定版（snapshot）**内一组选定地层的**无序两两关系**固化为一份
不可变成果包：

- 只列所选地层按编号排序的 C(n,2) 个地层对，不扩展出任何额外关系；
- 每个确定结论携带与该定版查询（GET /snapshots/{version}/relationship）
  完全一致的关系与**最优证据路径**，以及路径上按顺序排列的**原始断言**
  （取自定版内嵌断言快照，冻结该定版视角，不含后续状态）；
- 最优路径途经的未入选地层随证据原样保留在路径与断言里，但不会因此多出
  任何地层对；
- 未定关系不附支撑路径与断言（evidence_path/assertions 均为空数组）。

幂等与不可变：

- 同一 `(version, 地层集合)` 无论请求多少次、输入顺序如何，只有一份包
  （strata 存排序后数组，数据库唯一约束 + ON CONFLICT 幂等）；
- 包内容完全来自定版快照行，正式断言撤回、后续修订、新定版都不改写包内容；
  body 写入后永不修改、永不删除，并附规范化 sha256 供转交复核校验。

拒绝口径（不留半成品；所有校验与写入在同一事务，异常整体回滚）：

- 定版不存在 -> 404 SNAPSHOT_NOT_FOUND；
- 地层未登记（不在正式 strata 表）-> 400 INVALID_STRATUM；
- 输入为空（空列表或全空串）-> 400 EMPTY_SELECTION；
- 地层编号重复 -> 400 DUPLICATE_STRATUM；
- 去重后不足两个 -> 400 SELECTION_TOO_SMALL。
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from typing import Any, Dict, List, Optional, Sequence, Tuple

from psycopg2.extras import Json

from .db import db_conn
from .derivation import RELATION_LABELS
from .errors import ApiError
from .models import DossierIn


# ------------------------------------------------------------------ 校验
def _validate_selection(raw: Sequence[str]) -> List[str]:
    """校验并规范化入选地层：去空白判空、查重复、要求至少两个不重复值。

    返回按编号排序后的去重列表。校验顺序固定，避免一次请求里出现多个歧义错误。
    """
    # 空列表，或元素全为空串/纯空白
    if not raw or not any(isinstance(s, str) and s.strip() for s in raw):
        raise ApiError(
            400,
            "EMPTY_SELECTION",
            "地层集合为空：至少需要两个不重复的已登记地层编号",
        )
    blank = [s for s in raw if not isinstance(s, str) or not s.strip()]
    if blank:
        raise ApiError(
            400,
            "EMPTY_SELECTION",
            "地层编号不得为空",
            {"index": raw.index(blank[0])},
        )
    counts = Counter(raw)
    dupes = sorted(s for s, n in counts.items() if n > 1)
    if dupes:
        raise ApiError(
            400,
            "DUPLICATE_STRATUM",
            f"地层编号重复，成果包只接受不重复的地层集合: {dupes}",
            {"duplicates": dupes},
        )
    if len(raw) < 2:
        raise ApiError(
            400,
            "SELECTION_TOO_SMALL",
            f"至少需要两个不重复的地层编号，当前仅 {len(raw)} 个",
            {"count": len(raw)},
        )
    return sorted(raw)


# ------------------------------------------------------------------ 封存内容
def _pair_body(
    cur,
    version: int,
    a: str,
    b: str,
    assertions_by_id: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    """构建单个无序地层对 (a < b) 的封存内容。

    结论与最优路径直接读定版结论表，与该定版的关系查询同源；原始断言从
    定版内嵌断言快照按路径顺序展开（路径上的未入选地层随证据保留）。
    """
    cur.execute(
        "SELECT relation, path FROM snapshot_conclusions "
        "WHERE version = %s AND stratum_a = %s AND stratum_b = %s",
        (version, a, b),
    )
    row = cur.fetchone()
    if row is None:
        # 存疑兜底：结论表按有序对写入；若正向缺失则查反向并翻转方向。
        cur.execute(
            "SELECT relation, path FROM snapshot_conclusions "
            "WHERE version = %s AND stratum_a = %s AND stratum_b = %s",
            (version, b, a),
        )
        rev = cur.fetchone()
        if rev is None:
            relation, path = "undetermined", []
        else:
            relation = "later_than" if rev[0] == "earlier_than" else rev[0]
            path = list(rev[1])
    else:
        relation, path = row[0], list(row[1])

    if relation == "undetermined":
        # 未定关系不附支撑路径和断言
        return {
            "stratum_a": a,
            "stratum_b": b,
            "relation": relation,
            "relation_label": RELATION_LABELS[relation],
            "evidence_path": [],
            "assertions": [],
        }

    # 路径上的每条证据按顺序展开为该定版视角的原始断言。
    # 快照自包含：路径中的证据编号必然存在于定版断言快照，缺失只可能是数据损坏。
    detail: List[Dict[str, Any]] = []
    for eid in path:
        snap_a = assertions_by_id.get(eid)
        if snap_a is None:
            raise ApiError(
                500,
                "SNAPSHOT_CORRUPT",
                f"定版 {version} 的最优路径引用了快照内不存在的证据: {eid}",
                {"version": version, "evidence_id": eid},
            )
        detail.append(
            {
                "evidence_id": eid,
                "stratum_a": snap_a["stratum_a"],
                "stratum_b": snap_a["stratum_b"],
                "relation": snap_a["relation"],
            }
        )
    return {
        "stratum_a": a,
        "stratum_b": b,
        "relation": relation,
        "relation_label": RELATION_LABELS[relation],
        "evidence_path": path,
        "assertions": detail,
    }


def _canonical(body: Dict[str, Any]) -> bytes:
    """成果包内容的规范化字节表示（排序键、无空白），用于内容指纹。"""
    return json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


# ------------------------------------------------------------------ 创建（幂等）
def create_dossier(payload: DossierIn) -> Tuple[Dict[str, Any], bool]:
    """封存专题成果包。返回 (成果包, 是否新建)；同版同集合重复请求返回既有包。"""
    ordered_strata = _validate_selection(payload.strata)

    with db_conn() as conn:
        with conn.cursor() as cur:
            # 定版须存在；定版不可变，无需加锁。
            cur.execute(
                "SELECT revision, assertions FROM snapshots WHERE version = %s",
                (payload.version,),
            )
            snap = cur.fetchone()
            if snap is None:
                raise ApiError(
                    404,
                    "SNAPSHOT_NOT_FOUND",
                    f"定版不存在: {payload.version}",
                    {"version": payload.version},
                )
            snapshot_revision, snapshot_assertions = snap[0], list(snap[1])

            # 幂等快路径：同一定版与同一地层集合（与输入顺序无关）已有包则原样返回。
            cur.execute(
                "SELECT id FROM dossiers WHERE version = %s AND strata = %s FOR UPDATE",
                (payload.version, Json(ordered_strata)),
            )
            existing = cur.fetchone()
            if existing is not None:
                return _load_dossier(cur, existing[0]), False

            # 入选地层必须全部已登记（按当前登记表，与定版关系查询的校验口径一致）。
            cur.execute("SELECT stratum_id FROM strata WHERE stratum_id = ANY(%s)", (ordered_strata,))
            registered = {r[0] for r in cur.fetchall()}
            unknown = [s for s in ordered_strata if s not in registered]
            if unknown:
                raise ApiError(
                    400,
                    "INVALID_STRATUM",
                    f"地层未登记: {unknown}",
                    {"strata": unknown},
                )

            assertions_by_id = {a["evidence_id"]: a for a in snapshot_assertions}
            pairs: List[Dict[str, Any]] = []
            for i, a in enumerate(ordered_strata):
                for b in ordered_strata[i + 1 :]:
                    pairs.append(_pair_body(cur, payload.version, a, b, assertions_by_id))

            body = {
                "version": payload.version,
                "snapshot_revision": snapshot_revision,
                "strata": ordered_strata,
                "pairs": pairs,
            }
            content_hash = hashlib.sha256(_canonical(body)).hexdigest()

            # 唯一约束兜底并发：两个同时的首次请求只有一个插入成功，另一个转取既有包。
            cur.execute(
                "INSERT INTO dossiers (version, strata, body, content_hash) "
                "VALUES (%s, %s, %s, %s) ON CONFLICT (version, strata) DO NOTHING RETURNING id",
                (payload.version, Json(ordered_strata), Json(body), content_hash),
            )
            inserted = cur.fetchone()
            if inserted is None:
                cur.execute(
                    "SELECT id FROM dossiers WHERE version = %s AND strata = %s",
                    (payload.version, Json(ordered_strata)),
                )
                return _load_dossier(cur, cur.fetchone()[0]), False
            return _load_dossier(cur, inserted[0]), True


# ------------------------------------------------------------------ 读取
def _load_dossier(cur, dossier_id: int) -> Dict[str, Any]:
    cur.execute(
        "SELECT id, version, strata, body, content_hash, created_at FROM dossiers WHERE id = %s",
        (dossier_id,),
    )
    row = cur.fetchone()
    if row is None:
        raise ApiError(404, "DOSSIER_NOT_FOUND", f"成果包不存在: {dossier_id}", {"dossier_id": dossier_id})
    body = dict(row[3])
    return {
        "id": row[0],
        "version": row[1],
        "snapshot_revision": body.get("snapshot_revision"),
        "strata": list(row[2]),
        "pairs": body.get("pairs", []),
        "content_hash": row[4],
        "created_at": row[5].isoformat(),
    }


def get_dossier(dossier_id: int) -> Dict[str, Any]:
    with db_conn() as conn:
        with conn.cursor() as cur:
            return _load_dossier(cur, dossier_id)


def list_dossiers(version: Optional[int] = None) -> List[Dict[str, Any]]:
    """成果包列表（可按定版编号过滤）。仅列摘要，完整内容取单个成果包。"""
    with db_conn() as conn:
        with conn.cursor() as cur:
            if version is not None:
                cur.execute(
                    "SELECT id, version, strata, content_hash, created_at "
                    "FROM dossiers WHERE version = %s ORDER BY id",
                    (version,),
                )
            else:
                cur.execute(
                    "SELECT id, version, strata, content_hash, created_at FROM dossiers ORDER BY id"
                )
            return [
                {
                    "id": r[0],
                    "version": r[1],
                    "strata": list(r[2]),
                    "content_hash": r[3],
                    "created_at": r[4].isoformat(),
                }
                for r in cur.fetchall()
            ]
