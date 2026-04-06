"""walk_mm 계산 + zone_label 부여 + Main Artery Dijkstra + Semantic Tag + Virtual Entrance."""
import math

import networkx as nx
from shapely.geometry import LineString, Point, Polygon

from app.schemas.space_data import assign_zone_by_walk_mm
from app.agents.corridor_graph import build_corridor_graph, nearest_node, farthest_point


def assign_walk_mm(
    slots: dict[str, dict],
    entrance_mm: tuple[float, float],
    usable_poly: Polygon,
    dead_zones: list | None = None,
    all_entrances: list | None = None,
) -> LineString | None:
    """
    복수 입구 walk_mm 병렬 연산 + zone_label 부여 + Main Artery 반환.

    all_entrances: DetectedEntrance 리스트. 없으면 entrance_mm 단일 사용 (하위 호환).
    각 slot의 walk_mm = min(모든 입구로부터의 Dijkstra 거리).
    Main Artery = MAIN_DOOR↔EMERGENCY_EXIT 최단 경로 (없으면 MAIN↔farthest).
    """
    G, nodes = build_corridor_graph(usable_poly, dead_zones=dead_zones)
    if not nodes:
        return None

    # ── 복수 입구 좌표 수집 ─────────────────────────────────────────────────
    # all_entrances: [{"coord": (x_mm, y_mm), "type": str}, ...] (mm 정규화 좌표)
    # 또는 DetectedEntrance 객체 (하위 호환)
    entrance_coords: list[tuple[float, float]] = []
    entrance_types: list[str] = []

    if all_entrances:
        for ent in all_entrances:
            if isinstance(ent, dict):
                entrance_coords.append(ent["coord"])
                entrance_types.append(ent.get("type", "MAIN_DOOR"))
            elif hasattr(ent, "x_px"):
                entrance_coords.append((ent.x_px, ent.y_px))
                entrance_types.append(getattr(ent, "type", "MAIN_DOOR"))
            else:
                entrance_coords.append(ent)
                entrance_types.append("MAIN_DOOR")
        print(f"[Agent2] walk_mm: {len(entrance_coords)} entrances detected")
    else:
        entrance_coords.append(entrance_mm)
        entrance_types.append("MAIN_DOOR")

    # ── 각 입구별 Dijkstra → 슬롯별 min(거리) ───────────────────────────────
    all_lengths: list[dict] = []
    entrance_nodes: list[tuple[int, int]] = []

    for coord in entrance_coords:
        e_node = nearest_node(nodes, coord)
        entrance_nodes.append(e_node)
        try:
            lengths = nx.single_source_dijkstra_path_length(G, e_node, weight="weight")
            all_lengths.append(lengths)
        except nx.NetworkXError:
            all_lengths.append({})

    minx, miny, maxx, maxy = usable_poly.bounds
    max_walk = max(maxx - minx, maxy - miny)
    zone_1 = max_walk * 0.33
    zone_2 = max_walk * 0.66
    zones = {
        "entrance_zone": {"walk_mm_min": 0, "walk_mm_max": zone_1},
        "mid_zone": {"walk_mm_min": zone_1, "walk_mm_max": zone_2},
        "deep_zone": {"walk_mm_min": zone_2, "walk_mm_max": float("inf")},
    }

    for slot in slots.values():
        slot_node = nearest_node(nodes, (slot["x_mm"], slot["y_mm"]))
        # min(모든 입구로부터의 거리)
        min_walk = float("inf")
        for lengths in all_lengths:
            w = lengths.get(slot_node, float("inf"))
            if w < min_walk:
                min_walk = w
        if min_walk == float("inf"):
            min_walk = max_walk * 2
        slot["walk_mm"] = round(min_walk)
        slot["zone_label"] = assign_zone_by_walk_mm(min_walk, zones)

    # ── Main Artery: 관통 동선 식별 ──────────────────────────────────────────
    main_artery = _compute_main_artery(
        G, nodes, entrance_coords, entrance_types, entrance_nodes, usable_poly
    )
    return main_artery


def _compute_main_artery(
    G: nx.Graph,
    nodes: dict,
    entrance_coords: list[tuple[float, float]],
    entrance_types: list[str],
    entrance_nodes: list[tuple[int, int]],
    usable_poly: Polygon,
) -> LineString:
    """
    관통 동선(Main Artery) 계산.
    - MAIN_DOOR ↔ EMERGENCY_EXIT 쌍이 있으면 그 사이 최단 경로
    - 없으면 MAIN_DOOR ↔ farthest point
    - 입구 1개면 기존 로직 (입구 → farthest)
    """
    # MAIN과 EMERGENCY 찾기
    main_idx = None
    emergency_idx = None
    for i, t in enumerate(entrance_types):
        if t == "MAIN_DOOR" and main_idx is None:
            main_idx = i
        if t == "EMERGENCY_EXIT" and emergency_idx is None:
            emergency_idx = i

    if main_idx is None:
        main_idx = 0  # fallback: 첫 번째 입구

    # 관통 동선: MAIN ↔ EMERGENCY
    if emergency_idx is not None and emergency_idx != main_idx:
        try:
            path = nx.shortest_path(G, entrance_nodes[main_idx], entrance_nodes[emergency_idx], weight="weight")
            coords = [nodes[n] for n in path]
            if len(coords) >= 2:
                artery = LineString(coords)
                print(f"[Agent2] Main Artery: MAIN↔EMERGENCY Dijkstra {len(coords)} nodes, "
                      f"length={artery.length:.0f}mm")
                return artery
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            print("[Agent2] Main Artery: MAIN↔EMERGENCY path failed")

    # fallback: MAIN → Absolute Furthest Reachable Node (Dijkstra 거리 기준)
    # polygon 꼭짓점이 아닌, 실제 도달 가능한 그리드 노드 중 가장 먼 점
    main_node = entrance_nodes[main_idx]
    try:
        lengths = nx.single_source_dijkstra_path_length(G, main_node, weight="weight")
        if lengths:
            # Dijkstra 거리가 가장 큰 노드 = 입구에서 가장 먼 도달 가능 지점
            absolute_farthest = max(lengths.keys(), key=lambda k: lengths[k])
            path = nx.shortest_path(G, main_node, absolute_farthest, weight="weight")
            coords = [nodes[n] for n in path]
            if len(coords) >= 2:
                artery = LineString(coords)
                far_coord = nodes[absolute_farthest]
                print(f"[Agent2] Main Artery: MAIN→absolute farthest "
                      f"({far_coord[0]:.0f},{far_coord[1]:.0f}) "
                      f"Dijkstra {len(coords)} nodes, length={artery.length:.0f}mm, "
                      f"walk_dist={lengths[absolute_farthest]:.0f}mm")
                return artery
    except (nx.NetworkXNoPath, nx.NodeNotFound, nx.NetworkXError) as e:
        print(f"[Agent2] Main Artery: absolute farthest failed: {e}")

    # 최종 fallback: polygon 꼭짓점 기반
    main_coord = entrance_coords[main_idx]
    far_pt = farthest_point(usable_poly, main_coord)
    return LineString([main_coord, far_pt])


def assign_semantic_tags(
    slots: dict[str, dict],
    usable_poly: Polygon,
    entrance_mm: tuple[float, float] | None,
) -> None:
    """corner / wall_adjacent / center_area / entrance_facing 태그 부여."""
    coords = list(usable_poly.exterior.coords)
    minx, miny, maxx, maxy = usable_poly.bounds
    short_side = min(maxx - minx, maxy - miny)
    center_threshold = short_side * 0.3

    corner_vertices = []
    for i in range(len(coords) - 1):
        prev_i = (i - 1) % (len(coords) - 1)
        next_i = (i + 1) % (len(coords) - 1)
        dx1 = coords[i][0] - coords[prev_i][0]
        dy1 = coords[i][1] - coords[prev_i][1]
        dx2 = coords[next_i][0] - coords[i][0]
        dy2 = coords[next_i][1] - coords[i][1]
        len1 = math.hypot(dx1, dy1)
        len2 = math.hypot(dx2, dy2)
        if len1 > 0 and len2 > 0:
            cos_angle = (dx1 * dx2 + dy1 * dy2) / (len1 * len2)
            cos_angle = max(-1, min(1, cos_angle))
            angle = math.degrees(math.acos(cos_angle))
            if 60 <= angle <= 120:
                corner_vertices.append(coords[i])

    min_walk = min((s["walk_mm"] for s in slots.values()), default=0)
    tagged_count = 0

    for slot in slots.values():
        tags: list[str] = []
        sx, sy = slot["x_mm"], slot["y_mm"]
        slot_pt = Point(sx, sy)

        is_corner = any(math.hypot(sx - cx, sy - cy) < 500 for cx, cy in corner_vertices)
        if is_corner:
            tags.append("corner")

        wall_dist = usable_poly.exterior.distance(slot_pt)
        if not is_corner and wall_dist < 600:
            tags.append("wall_adjacent")
        if wall_dist > center_threshold:
            tags.append("center_area")

        if entrance_mm and min_walk > 0:
            if slot["walk_mm"] <= min_walk * 1.5:
                tags.append("entrance_facing")
        elif entrance_mm and slot["walk_mm"] == 0:
            tags.append("entrance_facing")

        slot["semantic_tags"] = tags
        if tags:
            tagged_count += 1

    print(f"[Agent2] semantic tags: {tagged_count}/{len(slots)} slots tagged, "
          f"corners={len(corner_vertices)}")


def build_virtual_entrance(
    entrance_mm: tuple[float, float],
    usable_poly: Polygon,
    entrance_width: float,
) -> tuple[LineString, Polygon]:
    """입구 → 외벽 edge → ±width/2 LineString + buffer 460mm."""
    coords = list(usable_poly.exterior.coords)
    entrance_pt = Point(entrance_mm)

    best_edge = None
    best_dist = float("inf")
    for i in range(len(coords) - 1):
        edge = LineString([coords[i], coords[i + 1]])
        dist = edge.distance(entrance_pt)
        if dist < best_dist:
            best_dist = dist
            best_edge = edge

    if not best_edge:
        half = entrance_width / 2
        line = LineString([
            (entrance_mm[0] - half, entrance_mm[1]),
            (entrance_mm[0] + half, entrance_mm[1]),
        ])
        return line, line.buffer(460)

    proj = best_edge.project(entrance_pt)
    half = entrance_width / 2
    start = max(0, proj - half)
    end = min(best_edge.length, proj + half)

    p_start = best_edge.interpolate(start)
    p_end = best_edge.interpolate(end)
    entrance_line = LineString([(p_start.x, p_start.y), (p_end.x, p_end.y)])
    buffer_poly = entrance_line.buffer(460, single_sided=False)

    return entrance_line, buffer_poly
