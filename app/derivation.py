"""地层关系推导引擎（纯 Python，无外部依赖）。

语义规则：
- 同一期（same_period）：对称、可传递，构成等价类（并查集）。
- 早于（earlier_than）：沿“同一期 + 早于”混合路径推导。
  若 x ~ a（同一期链）、a < b（早于）、b ~ y（同一期链），则 x 早于 y。
- 约束（对整批应用后的最终关系核验）：
  1. 组内早于禁止：同一等价类内不得存在（直接或间接的）早于关系；
  2. 早于闭环禁止：等价类商图上的早于关系必须是有向无环图（DAG）。

路径选取：证据数最少者优先；并列时按证据编号序列字典序最小者。
"""
from __future__ import annotations

import heapq
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

SAME = "same_period"
EARLIER = "earlier_than"

RELATION_LABELS = {
    "same_period": "同一期",
    "earlier_than": "早于",
    "later_than": "晚于",
    "undetermined": "未定",
}


@dataclass(frozen=True)
class Assertion:
    """一条生效中的断言。relation=earlier_than 表示 a 早于 b。"""

    evidence_id: str
    a: str
    b: str
    relation: str


class UnionFind:
    def __init__(self) -> None:
        self.parent: Dict[str, str] = {}
        self.rank: Dict[str, int] = {}

    def find(self, x: str) -> str:
        if x not in self.parent:
            self.parent[x] = x
            self.rank[x] = 0
            return x
        root = x
        while self.parent[root] != root:
            root = self.parent[root]
        # 路径压缩
        while self.parent[x] != root:
            self.parent[x], x = root, self.parent[x]
        return root

    def union(self, x: str, y: str) -> str:
        rx, ry = self.find(x), self.find(y)
        if rx == ry:
            return rx
        if self.rank[rx] < self.rank[ry]:
            rx, ry = ry, rx
        self.parent[ry] = rx
        if self.rank[rx] == self.rank[ry]:
            self.rank[rx] += 1
        return rx


def _build_adj(assertions: Iterable[Assertion], kinds: frozenset) -> Dict[str, List[Tuple[str, str]]]:
    """构建邻接表：同一期为无向边，早于是 a -> b 的有向边。边权为证据编号。"""
    adj: Dict[str, List[Tuple[str, str]]] = {}
    for a in assertions:
        if a.relation == SAME and SAME in kinds:
            adj.setdefault(a.a, []).append((a.b, a.evidence_id))
            adj.setdefault(a.b, []).append((a.a, a.evidence_id))
        elif a.relation == EARLIER and EARLIER in kinds:
            adj.setdefault(a.a, []).append((a.b, a.evidence_id))
    return adj


def best_path(adj: Dict[str, List[Tuple[str, str]]], start: str, goal: str) -> Optional[Tuple[str, ...]]:
    """Dijkstra，代价为 (证据数, 证据编号元组)，即先最少证据、再按编号字典序。

    返回证据编号序列（推导顺序），不可达返回 None。
    """
    if start == goal:
        return ()
    best: Dict[str, Tuple[int, Tuple[str, ...]]] = {start: (0, ())}
    pq: List[Tuple[Tuple[int, Tuple[str, ...]], str]] = [((0, ()), start)]
    while pq:
        cost, node = heapq.heappop(pq)
        if cost != best.get(node):
            continue
        if node == goal:
            return cost[1]
        for nxt, eid in adj.get(node, ()):
            ncost = (cost[0] + 1, cost[1] + (eid,))
            old = best.get(nxt)
            if old is None or ncost < old:
                best[nxt] = ncost
                heapq.heappush(pq, (ncost, nxt))
    return None


def _find_cycle(edges: Dict[str, List[Tuple[str, Assertion]]]) -> Optional[List[Assertion]]:
    """在等价类商图上找一个有向环，返回构成环的“早于”断言序列（沿环方向）。"""
    color: Dict[str, int] = {}  # 0/缺省=未访问 1=在栈上 2=已完成

    def ordered(n: str) -> List[Tuple[str, Assertion]]:
        return sorted(edges.get(n, []), key=lambda t: (t[1].evidence_id, t[0]))

    for start in sorted(edges):
        if color.get(start):
            continue
        color[start] = 1
        path_nodes: List[str] = [start]
        path_edges: List[Assertion] = []  # path_edges[i]: path_nodes[i] -> path_nodes[i+1]
        stack = [(start, iter(ordered(start)))]
        while stack:
            node, it = stack[-1]
            advanced = False
            for v, a in it:
                c = color.get(v, 0)
                if c == 0:
                    color[v] = 1
                    path_nodes.append(v)
                    path_edges.append(a)
                    stack.append((v, iter(ordered(v))))
                    advanced = True
                    break
                if c == 1:
                    idx = path_nodes.index(v)
                    return path_edges[idx:] + [a]
            if not advanced:
                color[node] = 2
                stack.pop()
                path_nodes.pop()
                if path_edges:
                    path_edges.pop()
    return None


class Derivation:
    """对一组生效断言的推导与核验。"""

    def __init__(self, assertions: Sequence[Assertion]) -> None:
        self.assertions: List[Assertion] = sorted(assertions, key=lambda a: a.evidence_id)
        self.uf = UnionFind()
        for a in self.assertions:
            self.uf.find(a.a)
            self.uf.find(a.b)
        for a in self.assertions:
            if a.relation == SAME:
                self.uf.union(a.a, a.b)
        self.same_adj = _build_adj(self.assertions, frozenset({SAME}))
        self.mixed_adj = _build_adj(self.assertions, frozenset({SAME, EARLIER}))

    # ------------------------------------------------------------------ 核验
    def validate(self) -> List[dict]:
        """核验最终关系，返回冲突列表（空列表表示通过）。"""
        conflicts: List[dict] = []

        # 1) 组内早于：早于断言两端落在同一等价类
        for a in self.assertions:
            if a.relation != EARLIER:
                continue
            if self.uf.find(a.a) == self.uf.find(a.b):
                chain = best_path(self.same_adj, a.a, a.b) or ()
                conflicts.append(
                    {
                        "type": "intra_group_earlier",
                        "message": (
                            f"证据 {a.evidence_id} 断言 {a.a} 早于 {a.b}，"
                            f"但同一期证据链表明二者同属一期（组内早于）"
                        ),
                        "evidence_path": list(chain) + [a.evidence_id],
                    }
                )

        # 2) 早于闭环：等价类商图上的有向环
        best_edge: Dict[Tuple[str, str], Assertion] = {}
        for a in self.assertions:
            if a.relation != EARLIER:
                continue
            ra, rb = self.uf.find(a.a), self.uf.find(a.b)
            if ra == rb:
                continue
            key = (ra, rb)
            if key not in best_edge or a.evidence_id < best_edge[key].evidence_id:
                best_edge[key] = a
        edges: Dict[str, List[Tuple[str, Assertion]]] = {}
        for (ra, rb), a in best_edge.items():
            edges.setdefault(ra, []).append((rb, a))

        cycle = _find_cycle(edges)
        if cycle:
            full_path: List[str] = []
            k = len(cycle)
            for i, cur in enumerate(cycle):
                nxt = cycle[(i + 1) % k]
                full_path.append(cur.evidence_id)
                full_path.extend(best_path(self.same_adj, cur.b, nxt.a) or ())
            conflicts.append(
                {
                    "type": "earlier_cycle",
                    "message": "早于关系形成闭环: "
                    + " -> ".join(f"{e.evidence_id}({e.a} 早于 {e.b})" for e in cycle),
                    "evidence_path": full_path,
                }
            )
        return conflicts

    # ------------------------------------------------------------------ 查询
    def relation(self, x: str, y: str) -> Tuple[str, Optional[List[str]]]:
        """返回 (关系, 证据路径)。关系 ∈ same_period / earlier_than / later_than / undetermined。"""
        if x == y:
            return "same_period", []
        if self.uf.find(x) == self.uf.find(y):
            path = best_path(self.same_adj, x, y) or ()
            return "same_period", list(path)
        p = best_path(self.mixed_adj, x, y)
        if p is not None:
            return "earlier_than", list(p)
        p = best_path(self.mixed_adj, y, x)
        if p is not None:
            return "later_than", list(p)
        return "undetermined", None
