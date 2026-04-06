"""NetworkX 보행 경로 그래프 + Choke Point 병목 탐지."""
import math

import networkx as nx
from shapely.geometry import LineString, Point, Polygon
from shapely.ops import unary_union

GRID_STEP_MM = 500
CHOKE_BUFFER_MM = 450


def build_corridor_graph(
    usable_poly: Polygon,
    step_mm: float = GRID_STEP_MM,
    dead_zones: list | None = None,
) -> tuple[nx.Graph, dict[tuple[int, int], tuple[float, float]]]:
    """격자 그래프 생성. dead_zones 내 노드 소거."""
    minx, miny, maxx, maxy = usable_poly.bounds
    obstacles = dead_zones or []

    G = nx.Graph()
    nodes: dict[tuple[int, int], tuple[float, float]] = {}

    xs = _frange(minx, maxx, step_mm)
    ys = _frange(miny, maxy, step_mm)
    for gx in xs:
        for gy in ys:
            pt = Point(gx, gy)
            if not usable_poly.contains(pt):
                continue
            if any(dz.contains(pt) for dz in obstacles):
                continue
            ix = round((gx - minx) / step_mm)
            iy = round((gy - miny) / step_mm)
            G.add_node((ix, iy))
            nodes[(ix, iy)] = (gx, gy)

    for (ix, iy) in list(G.nodes):
        for dix, diy in [(1, 0), (0, 1), (1, 1), (1, -1)]:
            nb = (ix + dix, iy + diy)
            if nb in G.nodes:
                dist = math.hypot(
                    nodes[nb][0] - nodes[(ix, iy)][0],
                    nodes[nb][1] - nodes[(ix, iy)][1],
                )
                G.add_edge((ix, iy), nb, weight=dist)

    dead_removed = sum(1 for gx in xs for gy in ys
                       if usable_poly.contains(Point(gx, gy))
                       and any(dz.contains(Point(gx, gy)) for dz in obstacles)) if obstacles else 0
    print(f"[Agent2] corridor graph: {len(nodes)} nodes, {G.number_of_edges()} edges"
          f"{f', {dead_removed} dead zone nodes removed' if dead_removed else ''}")

    return G, nodes


def detect_choke_points(
    usable_poly: Polygon,
    dead_zones: list,
    all_walls: list[LineString],
) -> list[Polygon]:
    """병목 구역 탐지. pairwise 거리 < 900mm인 쌍의 buffer 교집합."""
    raw_obstacles = []
    for wall in all_walls:
        if wall.length > 0:
            raw_obstacles.append(wall)
    for dz in dead_zones:
        if hasattr(dz, "boundary") and not dz.is_empty:
            raw_obstacles.append(dz)

    choke_points: list[Polygon] = []

    for i in range(len(raw_obstacles)):
        for j in range(i + 1, len(raw_obstacles)):
            try:
                gap = raw_obstacles[i].distance(raw_obstacles[j])
                if gap >= 900 or gap <= 0:
                    continue
                buf_i = raw_obstacles[i].buffer(CHOKE_BUFFER_MM)
                buf_j = raw_obstacles[j].buffer(CHOKE_BUFFER_MM)
                intersection = buf_i.intersection(buf_j)
                if intersection.is_empty or intersection.area < 100:
                    continue
                clipped = usable_poly.intersection(intersection)
                if clipped.is_empty or clipped.area < 100:
                    continue
                if clipped.geom_type == "MultiPolygon":
                    for geom in clipped.geoms:
                        if geom.area >= 100:
                            choke_points.append(geom)
                elif clipped.geom_type == "Polygon" and clipped.area >= 100:
                    choke_points.append(clipped)
            except Exception:
                continue

    max_choke_area = usable_poly.area * 0.05
    if choke_points:
        merged = unary_union(choke_points)
        if merged.geom_type == "MultiPolygon":
            choke_points = [g for g in merged.geoms if 100 <= g.area <= max_choke_area]
        elif merged.geom_type == "Polygon" and 100 <= merged.area <= max_choke_area:
            choke_points = [merged]
        else:
            choke_points = []

    return choke_points


def nearest_node(
    nodes: dict[tuple[int, int], tuple[float, float]],
    target: tuple[float, float],
) -> tuple[int, int]:
    return min(nodes.keys(), key=lambda k: math.hypot(
        nodes[k][0] - target[0], nodes[k][1] - target[1]
    ))


def farthest_point(poly: Polygon, origin: tuple[float, float]) -> tuple[float, float]:
    origin_pt = Point(origin)
    coords = list(poly.exterior.coords)
    return max(coords, key=lambda c: origin_pt.distance(Point(c)))


def _frange(start: float, stop: float, step: float) -> list[float]:
    result = []
    v = start
    while v <= stop:
        result.append(v)
        v += step
    return result
