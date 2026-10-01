#!/usr/bin/env bash
# 考古地层关系核验服务 —— 专题成果包端到端示例
# 前提：服务已启动（docker compose up --build），监听 http://localhost:8000
# 演示内容：定版封存 / 只列入选无序两两关系 / 最优路径与途经地层证据保留 /
#           与定版查询一致 / 未定不附路径 / 幂等（乱序同一份）/
#           撤回与新定版不改变旧包 / 各类输入明确拒绝不留半成品。
set -euo pipefail

BASE="${BASE_URL:-http://localhost:8000}"
pp() { python3 -m json.tool 2>/dev/null || cat; }
code() { curl -s -o /tmp/dossier_resp.json -w '%{http_code}' "$@" >/tmp/dossier_code; }

echo "== 0. 健康检查 =="
curl -s "$BASE/health" | pp

echo; echo "== 1. 登记地层 =="
for s in L1 L2 L3 L4 L5; do
  curl -s -X POST "$BASE/strata" -H 'Content-Type: application/json' \
    -d "{\"stratum_id\": \"$s\", \"site\": \"甲遗址\"}" | pp
done

echo; echo "== 2. 批次（修订号 0 -> 1）：L1~L2 同期，L2<L3，L3<L4，另有捷径 L2<L4 =="
curl -s -X POST "$BASE/batches" -H 'Content-Type: application/json' -d '{
  "expected_revision": 0,
  "operations": [
    {"op": "assert", "evidence_id": "EV-001", "stratum_a": "L1", "stratum_b": "L2", "relation": "same_period"},
    {"op": "assert", "evidence_id": "EV-002", "stratum_a": "L2", "stratum_b": "L3", "relation": "earlier_than"},
    {"op": "assert", "evidence_id": "EV-003", "stratum_a": "L3", "stratum_b": "L4", "relation": "earlier_than"},
    {"op": "assert", "evidence_id": "EV-010", "stratum_a": "L2", "stratum_b": "L4", "relation": "earlier_than"}
  ]}' | pp

echo; echo "== 3. 定版（记录版本号） =="
curl -s -X POST "$BASE/snapshots" -H 'Content-Type: application/json' \
  -d '{"label": "一期定版"}' | pp

echo; echo "== 4. 创建专题成果包：定版 1，入选地层 L1/L3/L4（首次 201） =="
code -X POST "$BASE/dossiers" -H 'Content-Type: application/json' \
  -d '{"version": 1, "strata": ["L1", "L3", "L4"]}'
echo "HTTP $(cat /tmp/dossier_code)"
cat /tmp/dossier_resp.json | pp
DID=$(python3 -c "import json;print(json.load(open('/tmp/dossier_resp.json'))['id'])")

echo; echo "== 4b. 包内 L1/L3 结论与定版查询逐条一致（路径含未入选的 L2） =="
curl -s "$BASE/snapshots/1/relationship?a=L1&b=L3" | pp

echo; echo "== 5. 未定对：L1 与 L5 无证据链，封存为未定（不附路径与断言） =="
curl -s -X POST "$BASE/dossiers" -H 'Content-Type: application/json' \
  -d '{"version": 1, "strata": ["L1", "L5"]}' | pp

echo; echo "== 6. 幂等：乱序重发同样集合 -> 200 reused=true，同一份包（id=$DID） =="
code -X POST "$BASE/dossiers" -H 'Content-Type: application/json' \
  -d '{"version": 1, "strata": ["L4", "L1", "L3"]}'
echo "HTTP $(cat /tmp/dossier_code)"
cat /tmp/dossier_resp.json | pp

echo; echo "== 7. 撤回 EV-002（修订 1 -> 2），当前 L1/L3 已变为未定 =="
curl -s -X POST "$BASE/batches" -H 'Content-Type: application/json' -d '{
  "expected_revision": 1,
  "operations": [{"op": "retract", "evidence_id": "EV-002"}]}' | pp
curl -s "$BASE/relationship?a=L1&b=L3" | pp

echo; echo "== 7b. 但成果包 id=$DID 内容不变（仍记录定版 1 的早于结论与证据） =="
curl -s "$BASE/dossiers/$DID" | pp

echo; echo "== 8. 再做新定版；旧包依旧不变 =="
curl -s -X POST "$BASE/snapshots" -H 'Content-Type: application/json' \
  -d '{"label": "二期定版"}' | pp
curl -s "$BASE/dossiers/$DID" | pp

echo; echo "== 9. 列表（可按定版过滤） =="
curl -s "$BASE/dossiers" | pp
curl -s "$BASE/dossiers?version=1" | pp

echo; echo "== 10. 拒绝场景（均不生成半成品） =="
echo "-- 10.1 定版不存在（404 SNAPSHOT_NOT_FOUND） --"
code -X POST "$BASE/dossiers" -H 'Content-Type: application/json' -d '{"version": 999, "strata": ["L1", "L2"]}'
echo "HTTP $(cat /tmp/dossier_code)"; cat /tmp/dossier_resp.json | pp

echo "-- 10.2 地层未登记（400 INVALID_STRATUM） --"
code -X POST "$BASE/dossiers" -H 'Content-Type: application/json' -d '{"version": 1, "strata": ["L1", "LX"]}'
echo "HTTP $(cat /tmp/dossier_code)"; cat /tmp/dossier_resp.json | pp

echo "-- 10.3 输入为空（400 EMPTY_SELECTION） --"
code -X POST "$BASE/dossiers" -H 'Content-Type: application/json' -d '{"version": 1, "strata": []}'
echo "HTTP $(cat /tmp/dossier_code)"; cat /tmp/dossier_resp.json | pp

echo "-- 10.4 仅一个地层（400 SELECTION_TOO_SMALL） --"
code -X POST "$BASE/dossiers" -H 'Content-Type: application/json' -d '{"version": 1, "strata": ["L1"]}'
echo "HTTP $(cat /tmp/dossier_code)"; cat /tmp/dossier_resp.json | pp

echo "-- 10.5 地层重复（400 DUPLICATE_STRATUM） --"
code -X POST "$BASE/dossiers" -H 'Content-Type: application/json' -d '{"version": 1, "strata": ["L1", "L1", "L2"]}'
echo "HTTP $(cat /tmp/dossier_code)"; cat /tmp/dossier_resp.json | pp

echo; echo "== 11. 成果包不存在（404 DOSSIER_NOT_FOUND） =="
curl -s "$BASE/dossiers/987654" | pp

echo; echo "全部示例执行完毕。"
