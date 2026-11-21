"""空间距离索引：由 SpatialConfig 构建全节点最短耗时（TU）。"""

from __future__ import annotations

import heapq


class SpatialIndex:
    """全源最短路径。边来自 distance_edges（双向）+ 各节点 travel_cost_from_well_tu（连到 well）。"""

    def __init__(self, spatial) -> None:
        self._dist: dict[tuple[str, str], float] = {}
        self._build(spatial)

    def _build(self, spatial) -> None:
        nodes = {n.id for n in spatial.nodes}
        adj: dict[str, list[tuple[str, float]]] = {n: [] for n in nodes}
        for e in spatial.distance_edges:
            w = float(e.one_way_tu)
            adj.setdefault(e.from_id, []).append((e.to_id, w))
            adj.setdefault(e.to_id, []).append((e.from_id, w))
        well = "well"
        for n in spatial.nodes:
            cost = getattr(n, "travel_cost_from_well_tu", None)
            if cost is not None and n.id != well:
                adj.setdefault(n.id, []).append((well, float(cost)))
                adj.setdefault(well, []).append((n.id, float(cost)))
        for src in nodes:
            self._dijkstra(src, adj)

    def _dijkstra(self, src: str, adj: dict[str, list[tuple[str, float]]]) -> None:
        dist: dict[str, float] = {src: 0.0}
        pq: list[tuple[float, str]] = [(0.0, src)]
        while pq:
            d, u = heapq.heappop(pq)
            if d > dist.get(u, float("inf")):
                continue
            for v, w in adj.get(u, []):
                nd = d + w
                if nd < dist.get(v, float("inf")):
                    dist[v] = nd
                    heapq.heappush(pq, (nd, v))
        for v, d in dist.items():
            self._dist[(src, v)] = d

    def travel_tu(self, a: str, b: str) -> float:
        if a == b:
            return 0.0
        return self._dist.get((a, b), float("inf"))
