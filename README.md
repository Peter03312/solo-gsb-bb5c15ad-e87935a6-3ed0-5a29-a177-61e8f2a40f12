# 考古地层关系核验服务

基于 **Python (FastAPI) + PostgreSQL** 的考古地层关系核验服务。登记遗址地层与带唯一证据编号的
“同一期 / 早于”断言，自动推导地层间关系，支持批次原子核验、冲突证据路径定位、关系查询与不可变定版快照。

## 语义规则

- **同一期（same_period）**：对称且可传递，构成等价类。
- **早于（earlier_than）**：沿“同一期 + 早于”混合路径推导。
  例如 `L1 ~ L2`（同一期）、`L2 < L3`（早于），则 `L1 早于 L3`。
- **硬约束**（对整批应用后的最终关系核验）：
  1. **组内早于禁止**——同一期等价类内部不得存在早于关系；
  2. **早于闭环禁止**——等价类之间的早于关系不得成环。
- **批次语义**：每批新增/撤回须携带当前修订号；按整批应用后的最终关系核验；
  发生矛盾时**整批拒绝**并返回冲突证据路径，原状态不变；全部通过则在同一事务内落库并**原子递增修订号**。
- **路径选取**：多条证据路径时，取证据数最少者；并列时按证据编号序列字典序最小者。
- **定版（快照）**：保存当前修订号下全部关系结论的不可变快照；后续撤回不影响旧版结论。
- **专题成果包**：把某定版中的一组（≥2、不重复、已登记）地层封存为不可变、可转交
  复核包：只含按编号排序的无序两两关系，结论与最优路径同该定版查询，确定结论携带
  路径按序原始断言，途经未入选地层随证据保留但不扩展关系，未定不附路径；同一定版 +
  同一地层集合（顺序无关）只封存一份，撤回 / 新修订 / 新定版均不改变包内容。
- **修订变化追踪**：对每次成功的正式断言批次及推演并入产生的正式修订，记录提交前后
  关系结论或最优支撑路径发生变化的地层对；同一对按地层编号固定顺序只列一次；
  关系不变但最优路径改变也记录；变为未定时路径为空。记录与批次同事务原子写入，
  失败批次、推演内编辑、无净变更并入不产生记录；已有历史修订在服务启动时幂等回填。
- **推演（沙盘）**：创建时固定当前正式修订号、已登记地层与生效断言；推演内沿用正式批次的
  新增 / 撤回 / 整批核验语义（携带推演自身修订号），正式状态始终不变。提交（并入）时把推演
  **相对基线的净变更**应用于最新正式状态并重新核验：基线目标已撤回 / 编号已被正式占用 /
  关系冲突（附证据路径）时返回具体原因且双方不变；通过则作为一次正式批次原子提交并关闭推演；
  净变更为空时只关闭推演，不递增正式修订号。

## 快速开始

```bash
docker compose up --build
```

- API 地址：**http://localhost:8000**
- 交互式接口文档（Swagger UI）：**http://localhost:8000/docs**
- PostgreSQL：`localhost:5432`（容器内服务名 `db`，数据持久化于命名卷 `pgdata`）

首次启动时应用会自动等待数据库就绪并完成表结构初始化，无需手工迁移。

### 配置

| 环境变量 | 默认值 | 说明 |
| --- | --- | --- |
| `DATABASE_URL` | `postgresql://strat:strat@db:5432/stratigraphy`（compose 内） | 应用连接串 |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | `strat` / `strat` / `stratigraphy` | 数据库账号（compose） |
| `APP_PORT` | `8000` | API 对外端口 |
| `DB_PORT` | `5432` | 数据库对外端口 |

本地开发（不用 Docker）：

```bash
pip install -r requirements.txt
export DATABASE_URL=postgresql://strat:strat@localhost:5432/stratigraphy
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## API 一览

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/strata` | 登记地层 `{stratum_id, site?}` |
| GET | `/strata` | 地层列表 |
| POST | `/batches` | 提交一批断言新增/撤回（整批核验，成功原子递增修订号） |
| GET | `/revision` | 当前修订号 |
| GET | `/assertions?status=active` | 断言列表 |
| GET | `/revision-changes?limit=100&cursor=...` | 游标分页追踪各正式修订前后关系/最优路径变化 |
| GET | `/relationship?a=L1&b=L3` | 查询两地层当前关系及支撑证据路径 |
| POST | `/snapshots` | 定版：保存不可变关系快照 `{label?}` |
| GET | `/snapshots` / `/snapshots/{version}` | 版本列表 / 版本详情 |
| GET | `/snapshots/{version}/relationship?a=L1&b=L3` | 查询历史版本结论 |
| POST | `/projections` | 创建推演（固定当前修订号、地层与生效断言） `{label?}` |
| GET | `/projections` / `/projections/{id}` | 推演列表 / 推演详情（含净变更） |
| POST | `/projections/{id}/batches` | 推演内提交批次（携带推演修订号，语义同正式批次） |
| GET | `/projections/{id}/relationship?a=L1&b=L3` | 查询推演视角下的关系与证据路径 |
| POST | `/projections/{id}/merge` | 并入：净变更应用于最新正式状态并重新核验 |
| DELETE | `/projections/{id}` | 放弃推演（仅 open 可放弃） |
| POST | `/packages` | 封存专题成果包：把定版中的一组地层关系冻结为可转交复核包 `{version, strata[]}` |
| GET | `/packages` / `/packages/{id}` | 成果包列表 / 成果包详情（冻结内容与内容指纹） |

### 批次请求格式

```json
{
  "expected_revision": 0,
  "operations": [
    {"op": "assert", "evidence_id": "EV-001", "stratum_a": "L1", "stratum_b": "L2", "relation": "same_period"},
    {"op": "assert", "evidence_id": "EV-002", "stratum_a": "L2", "stratum_b": "L3", "relation": "earlier_than"},
    {"op": "retract", "evidence_id": "EV-009"}
  ]
}
```

- `relation`：`same_period`（同一期）/ `earlier_than`（`stratum_a` 早于 `stratum_b`）。
- 成功响应：`{"revision": 1, "applied": 3, "relation_changes": 3}`
  （`relation_changes` 为本修订导致关系或最优支撑路径变化的地层对数，可能为 0）。
- 冲突响应（HTTP 409，原状态不变）：

```json
{
  "error": {
    "code": "CONFLICT",
    "message": "批次与现有断言矛盾，整批拒绝，原状态不变",
    "details": {
      "conflicts": [
        {"type": "earlier_cycle", "message": "早于关系形成闭环: ...", "evidence_path": ["EV-002", "EV-003", "EV-004"]}
      ]
    }
  }
}
```

### 关系查询响应

```json
{
  "stratum_a": "L1",
  "stratum_b": "L3",
  "relation": "earlier_than",
  "relation_label": "早于",
  "evidence_path": ["EV-001", "EV-002"],
  "path_detail": [
    {"evidence_id": "EV-001", "stratum_a": "L1", "stratum_b": "L2", "relation": "same_period", "status": "active"},
    {"evidence_id": "EV-002", "stratum_a": "L2", "stratum_b": "L3", "relation": "earlier_than", "status": "active"}
  ],
  "revision": 1
}
```

`relation` 取值：`same_period`（同一期）/ `earlier_than`（早于）/ `later_than`（晚于）/ `undetermined`（未定）。

### 错误码

| HTTP | code | 含义 |
| --- | --- | --- |
| 400 | `INVALID_STRATUM` | 引用了未登记的地层 |
| 409 | `STALE_REVISION` | 批次携带的修订号过期（响应含当前修订号） |
| 409 | `DUPLICATE_EVIDENCE` | 证据编号重复（含已撤回的编号） |
| 409 | `ASSERTION_NOT_FOUND` | 撤回不存在或已撤回的断言 |
| 409 | `CONFLICT` | 整批核验发现组内早于 / 早于闭环（附冲突证据路径） |
| 409 | `STRATUM_EXISTS` | 地层重复登记 |
| 404 | `SNAPSHOT_NOT_FOUND` | 版本不存在 |
| 404 | `PROJECTION_NOT_FOUND` | 推演不存在 |
| 409 | `PROJECTION_CLOSED` | 推演已关闭（merged/discarded），不可再操作 |
| 409 | `MERGE_TARGET_RETRACTED` | 并入失败：撤回目标证据已在最新正式状态被撤回 |
| 409 | `MERGE_EVIDENCE_TAKEN` | 并入失败：推演新增证据编号已被正式历史占用 |
| 409 | `MERGE_CONFLICT` | 并入核验发现关系冲突（附冲突证据路径），双方不变 |
| 400 | `INVALID_CURSOR` | 变化追踪分页游标无效 |
| 400 | `EMPTY_STRATA` | 成果包：地层集合为空 |
| 400 | `NOT_ENOUGH_STRATA` | 成果包：少于两个地层编号 |
| 400 | `DUPLICATE_STRATUM` | 成果包：地层编号重复 |
| 404 | `PACKAGE_NOT_FOUND` | 成果包不存在 |

## 正式修订关系变化追踪

考古人员需要按正式修订追踪**关系结论及支撑证据**的变化。服务对每次成功的
**正式断言批次**（`POST /batches`）与**推演并入产生的正式修订**
（`POST /projections/{id}/merge` 且实际递增修订号）记录变化明细。

**记录口径**

- 同一地层对按地层编号固定顺序只列一次：返回中恒有 `stratum_a < stratum_b`；
- 记录条件：提交前后**关系变化**（同一期 / 早于 / 晚于 / 未定之间）**或**
  关系不变但**最优支撑路径改变**（路径选取沿用现有规则：证据数最少、并列按证据
  编号序列字典序最小）；
- 变为未定时新路径为空数组 `[]`；首版从未定变为确定结论时旧路径也为 `[]`；
- 旧侧关系与路径按**该修订提交前的当时状态**推导：后来才被撤回的证据在旧侧仍按
  当时生效解释（无需回放后续撤回）；
- **失败批次不产生记录**（整批拒绝、原状态不变、修订号不增）；
  **推演内编辑不产生正式记录**（只动 `projection_*` 表）；
  **无净变更并入不产生记录**（只关闭推演、不递增正式修订号）；
- 成功修订也可能零变化（如撤回一条从未进入最优路径的平行断言）：修订号照常递增、
  审计与封口照写，但没有变化行。

**原子性与并发**

- 变化记录与断言落库、修订号递增在**同一事务**内提交，读不到“半批结果”；
  每次成功批次对计数器行加排他锁，并发提交串行化，修订号连续、不重不漏。

**游标分页** `GET /revision-changes`

- 参数：`limit`（每页 1–1000，默认 100）、`cursor`（首屏省略，后续原样回传
  上一页的 `next_cursor`，为不透明令牌）；
- **同一轮固定正式修订上界**：首屏把当前修订号固定为 `bound_revision` 并编码进
  游标；翻页期间发生的并发提交不会进入本轮窗口，因此整轮遍历不漏项、不重复；
  本轮读完（`has_more=false`、`next_cursor=null`）后重新发一个不带 `cursor` 的
  首屏请求，即可开启覆盖新修订的下一轮；
- 每页在 `REPEATABLE READ READ ONLY` 快照事务内读取。

响应示例：

```json
{
  "changes": [
    {
      "revision": 1,
      "stratum_a": "L1",
      "stratum_b": "L3",
      "old_relation": "undetermined",
      "new_relation": "earlier_than",
      "old_relation_label": "未定",
      "new_relation_label": "早于",
      "old_evidence_path": [],
      "new_evidence_path": ["EV-001", "EV-002"],
      "source": "formal_batch"
    }
  ],
  "bound_revision": 1,
  "limit": 100,
  "has_more": false,
  "next_cursor": null
}
```

`source`：`formal_batch`（正式断言批次）/ `projection_merge`（推演并入产生的
正式修订）。

**历史修订可追溯**：服务启动时幂等检查 `revisions` 审计，对部署前已存在、尚未
追踪的历史修订按当时断言集（`added_revision` / `retracted_revision` 回放）重算
旧/新关系与最优路径并回填；推演并入的历史修订 `source` 按审计记录还原为
`projection_merge`。再次启动不会重复（按修订封口）。

```bash
# 首屏
curl "$BASE/revision-changes?limit=100"
# 翻页：原样回传 next_cursor
curl "$BASE/revision-changes?limit=100&cursor=eyJiIjo1LCJyIjoxLCJzIjozLCJ2IjoxfQ"

# 完整端到端示例（含失败批次 / 推演并入 / 路径变化 / 分页上界）
bash examples/changes_demo.sh
```

## 推演（证据修订沙盘）

考古人员可在**不改动正式断言**的前提下推演证据修订：

1. **创建即固定基线**：`base_revision`（正式修订号）、`base_strata`（已登记地层）、
   `base_assertions`（生效断言快照）。推演创建之后正式侧新增的地层 / 断言对该推演不可见。
2. **推演内批次语义与正式批次一致**：
   - 请求携带的是**推演修订号**（自 0 起，每次成功批次 +1），过期返回 `STALE_REVISION`；
   - 按整批应用后的推演最终关系核验，组内早于 / 早于闭环整批拒绝，附冲突证据路径；
   - **正式历史已用证据编号不可复用**（含已撤回，查正式 `assertions`），
     **推演新增编号在本推演内不可复用**（含在推演内已撤回）；
   - 可撤回推演自己新增的断言，也可撤回基线断言；撤回同样只置状态、不可重复。
3. **推演查询**：`GET /projections/{id}/relationship` 返回推演视角下的关系与证据路径，
   `path_detail[].scope` 标注每步证据来源：`base`（基线）/ `projection`（推演新增）。
4. **并入（merge）**：把推演相对基线的**净变更**（推演内仍生效的新增 + 被撤回的基线断言；
   “新增后又撤回”不产生净变更）应用到**最新**正式状态并重新核验：
   - 基线撤回目标已在正式状态撤回 → `MERGE_TARGET_RETRACTED`；
   - 新增编号已被正式占用 → `MERGE_EVIDENCE_TAKEN`；
   - 净变更应用后出现组内早于 / 早于闭环 → `MERGE_CONFLICT`（附证据路径）；
   - 任一失败：**正式状态与推演均不变**。
   - 核验通过：作为一次正式批次原子提交（写 `assertions`、`revisions` 审计，
     批次记录带来源 `source=projection_merge`），正式修订号 +1 并关闭推演；
     该修订的关系变化同样可在 `/revision-changes` 追踪（`source=projection_merge`）；
   - 净变更为空：只关闭推演，**不递增正式修订号**。
5. 并入与放弃都会关闭推演；关闭后其冻结视图仍可查询，但不能再提交批次或并入。

### 推演请求示例

创建并查询：

```bash
curl -X POST "$BASE/projections" -H 'Content-Type: application/json' \
  -d '{"label": "二期证据修订推演"}'
# -> {"id": 1, "base_revision": 1, "projection_revision": 0, "status": "open", ...}

curl "$BASE/projections/1/relationship?a=L1&b=L3"
```

推演内批次（`expected_revision` 为推演修订号）：

```bash
curl -X POST "$BASE/projections/1/batches" -H 'Content-Type: application/json' -d '{
  "expected_revision": 0,
  "operations": [
    {"op": "retract", "evidence_id": "EV-002"},
    {"op": "assert", "evidence_id": "EV-P01", "stratum_a": "L4", "stratum_b": "L5", "relation": "earlier_than"}
  ]}'
# -> {"id": 1, "projection_revision": 1, "applied": 2}（正式状态不变）
```

并入：

```bash
curl -X POST "$BASE/projections/1/merge"
# 成功 -> {"id": 1, "merged": true, "applied": 2, "revision": 2,
#          "revision_incremented": true, "relation_changes": 3,
#          "net_changes": {"added": [...], "retracted": [...], "count": 2}}
# 冲突 -> HTTP 409 MERGE_CONFLICT，details.conflicts[].evidence_path 给出证据路径
```

完整流程（含正式状态不受影响、编号复用拒绝、三类并入失败、空净变更只关闭）见
`examples/projection_demo.sh`：

```bash
bash examples/projection_demo.sh
```

## 专题成果包（定版地层关系封存转交）

考古人员可把**某个定版**中的一组地层关系封存为可转交复核的专题成果包。成果包是
**定版时刻的只读摘录**，独立于正式状态继续演化。

**封存口径**

- 请求给出定版编号 `version` 与至少两个、不重复的**已登记**地层编号 `strata`；
- 包内只列所选地层**按编号排序**后的无序两两关系（每对取编号较小者为
  `stratum_a`，`stratum_a < stratum_b`）；
- 关系结论与最优证据路径与**该定版查询**（`GET /snapshots/{version}/relationship`）
  严格一致：确定关系直接取自定版冻结结论，路径为该定版选取的最优证据序列
  （证据数最少、并列按证据编号字典序最小）；
- 每条确定结论的 `path_detail` 携带路径上**按顺序**的原始断言（证据编号、两端
  地层、关系），原始断言取自**定版冻结的断言副本**（`snapshots.assertions`），
  不读取在线断言表，因此其 `status` 恒为封存时的 `active`；
- 路径**途经但未入选**的地层只随证据保留：包顶层给出 `transit_strata`，每步断言
  用 `in_selection`（该步两端是否都在入选集合内）标注；不会因为途经而扩展出
  额外的两两关系；
- **未定关系**只返回 `relation=undetermined` 与中文标签，**不附** `evidence_path`
  和 `path_detail`；
- `evidence` 是包内所有路径引用到的去重原始断言清单（按证据编号排序），便于脱离
  本服务转交复核；`content_hash` 是包内容（定版、修订、入选集合、pairs、evidence、
  transit_strata）的 sha256 指纹，接收方可据此校验包未被篡改。

**身份与不可变性**

- 同一 `version` + **同一地层集合**无论输入顺序、是否重复输入，都只生成**一份**
  成果包（按排序去重后的集合取指纹 `strata_key`，数据库唯一约束
  `(version, strata_key)` 保证；并发封存也在行锁下串行）；
- 首次封存返回 **HTTP 201**；同集合重复封存幂等返回**同一份**（相同 `id` 与
  `content_hash`），HTTP **200**，响应带 `already_exists=true`；
- 包内容在封存事务内一次性冻结，之后**永不修改、永不删除**：正式断言撤回、后续
  修订、新定版都不会改变已有包（旧包仍展示定版当时的结论与当时生效断言）。

**拒绝语义（校验失败明确拒绝、事务回滚，不留半成品）**

| 情形 | HTTP | code |
| --- | --- | --- |
| `strata` 为空 | 400 | `EMPTY_STRATA` |
| 少于两个地层 | 400 | `NOT_ENOUGH_STRATA` |
| 地层编号重复 | 400 | `DUPLICATE_STRATUM` |
| 含空编号 / 地层未登记 | 400 | `INVALID_STRATUM` |
| 定版不存在 | 404 | `SNAPSHOT_NOT_FOUND` |
| 缺少 `version`/`strata` 字段、类型不符 | 422 | FastAPI 请求体校验 |

### 封存请求与响应

```bash
# 选 L1、L5、L6；L1 早于 L5 的证据链途经未入选的 L2、L3、L4
curl -X POST "$BASE/packages" -H 'Content-Type: application/json' \
  -d '{"version": 1, "strata": ["L1", "L5", "L6"]}'
```

```json
{
  "id": 1,
  "version": 1,
  "snapshot_revision": 1,
  "label": "二期定版",
  "strata": ["L1", "L5", "L6"],
  "pairs": [
    {
      "stratum_a": "L1",
      "stratum_b": "L5",
      "relation": "earlier_than",
      "relation_label": "早于",
      "evidence_path": ["EV-001", "EV-002", "EV-003", "EV-004"],
      "path_detail": [
        {"evidence_id": "EV-001", "stratum_a": "L1", "stratum_b": "L2", "relation": "same_period", "status": "active", "in_selection": false},
        {"evidence_id": "EV-002", "stratum_a": "L2", "stratum_b": "L3", "relation": "earlier_than", "status": "active", "in_selection": false},
        {"evidence_id": "EV-003", "stratum_a": "L3", "stratum_b": "L4", "relation": "earlier_than", "status": "active", "in_selection": false},
        {"evidence_id": "EV-004", "stratum_a": "L4", "stratum_b": "L5", "relation": "same_period", "status": "active", "in_selection": false}
      ]
    },
    {"stratum_a": "L1", "stratum_b": "L6", "relation": "earlier_than", "relation_label": "早于", "...": "..."},
    {"stratum_a": "L5", "stratum_b": "L6", "relation": "undetermined", "relation_label": "未定"}
  ],
  "evidence": [
    {"evidence_id": "EV-001", "stratum_a": "L1", "stratum_b": "L2", "relation": "same_period", "status": "active"}
  ],
  "transit_strata": ["L2", "L3", "L4"],
  "content_hash": "cfa6dd4e0236a56f9b4f18f1fbeeaed6f8913451d2329ac46f007f05d379fd15",
  "created_at": "2026-10-01T01:24:31.192399+00:00",
  "already_exists": false
}
```

- 乱序等价：`{"version":1,"strata":["L6","L1","L5"]}` 与上例是**同一个集合**，
  返回同一 `id`、同一 `content_hash`（HTTP 200，`already_exists=true`）；
- 列表 `GET /packages` 只给摘要（不含 `pairs` 明细）；
  详情 `GET /packages/{id}` 返回完整冻结内容，不存在返回 404 `PACKAGE_NOT_FOUND`。

完整端到端演示（封存、乱序幂等、未定无路径、撤回 + 新定版后内容不变、各类拒绝）：

```bash
bash examples/packages_demo.sh
```

## 调用示例

端到端 curl 演示（覆盖登记、批次、推导查询、冲突拒绝、撤回、定版与旧版不可变）：

```bash
bash examples/demo.sh
```

推演（沙盘）端到端演示（创建固定基线、推演批次、关系查询、并入成功与三类并入失败、
净变更为空只关闭、放弃推演）：

```bash
bash examples/projection_demo.sh
```

正式修订关系变化追踪演示（正式批次 / 路径变化 / 失败批次不产生记录 /
推演内编辑与并入 / 游标分页与同一轮上界）：

```bash
bash examples/changes_demo.sh
```

专题成果包封存演示（定版选层封存、路径途经未入选地层、乱序幂等一份、
未定不附路径、撤回与新定版后不可变、空 / 重复 / 未登记 / 定版不存在明确拒绝）：

```bash
bash examples/packages_demo.sh
```

Python 客户端示例：

```bash
pip install requests
python3 examples/client_demo.py
```

## 项目结构

```
app/
  main.py         # FastAPI 路由与错误处理
  service.py      # 正式批次核验、关系查询、定版快照
  packages.py     # 专题成果包：定版地层关系封存（冻结、集合幂等、不可变、可转交复核）
  projections.py  # 推演（沙盘）：创建固定基线、推演批次、关系查询、并入核验
  changes.py      # 正式修订变化追踪：前后差异计算、游标分页、启动历史回填
  derivation.py   # 推导引擎：并查集等价类、DAG 校验、最优证据路径
  db.py           # 连接池与模式初始化（启动时自动建表、幂等回填）
  models.py       # 请求模型
examples/
  demo.sh           # curl 端到端示例（批次/查询/冲突/撤回/定版）
  projection_demo.sh # 推演端到端示例（沙盘批次、并入成功与三类失败、空净变更）
  changes_demo.sh  # 修订变化追踪示例（变化/路径改变/失败批次/并入/游标分页）
  packages_demo.sh # 专题成果包示例（封存/幂等/不可变/拒绝分支）
  client_demo.py    # Python 客户端示例
Dockerfile
docker-compose.yml
requirements.txt
```
