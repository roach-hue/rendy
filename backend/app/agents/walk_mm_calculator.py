"""walk_mm 계산 + zone_label 부여 + Main Artery Dijkstra + Semantic Tag + Virtual Entrance."""
import math

import networkx as nx
from shapely.geometry import LineString, Point, Polygon

from app.schemas.space_data import assign_zone_by_walk_mm
from app.agents.corridor_graph import build_corridor_graph, nearest_node


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

    # MAIN_DOOR 기준 Dijkstra = zone_label 산출용 (VMD 위계 유지)
    # walk_mm = min(전체 입구) (접근성), zone_label = MAIN 기준 (동선 위계)
    main_idx = 0
    for i, t in enumerate(entrance_types):
        if t == "MAIN_DOOR":
            main_idx = i
            break
    main_lengths = all_lengths[main_idx] if main_idx < len(all_lengths) else {}

    for slot in slots.values():
        slot_node = nearest_node(nodes, (slot["x_mm"], slot["y_mm"]))
        # walk_mm = min(모든 입구로부터의 거리) — 접근성
        min_walk = float("inf")
        for lengths in all_lengths:
            w = lengths.get(slot_node, float("inf"))
            if w < min_walk:
                min_walk = w
        if min_walk == float("inf"):
            min_walk = max_walk * 2
        slot["walk_mm"] = round(min_walk)

        # zone_label = MAIN_DOOR 기준 거리 — VMD 위계 (입구→mid→deep 단방향)
        main_walk = main_lengths.get(slot_node, max_walk * 2)
        slot["zone_label"] = assign_zone_by_walk_mm(main_walk, zones)

    # ── Main Artery: 관통 동선 식별 ──────────────────────────────────────────
    main_artery = _compute_main_artery(
        G, nodes, entrance_coords, entrance_types, usable_poly
    )

    return main_artery


def _compute_main_artery(
    G: nx.Graph,
    nodes: dict,
    entrance_coords: list[tuple[float, float]],
    entrance_types: list[str],
    usable_poly: Polygon,
) -> LineString:
    """
    VMD 정석 주동선(Main Spine) 생성.

    단일 입구: 입구 → 바닥 중심 → 최원 벽면 중앙 (직각 ㄱ자)
    복수 입구 (MAIN + EMERGENCY): 입구 → deep wall 경유 → 출구 (관통 동선)

    대각선 금지 — 직진 또는 ㄱ자 직각 형태만 허용.
    """
    main_idx = None
    emergency_idx = None
    for i, t in enumerate(entrance_types):
        if t == "MAIN_DOOR" and main_idx is None:
            main_idx = i
        if t == "EMERGENCY_EXIT" and emergency_idx is None:
            emergency_idx = i
    if main_idx is None:
        main_idx = 0

    entrance = entrance_coords[main_idx]

    # 복수 입구: MAIN → deep wall 경유 → EMERGENCY (관통 동선)
    if emergency_idx is not None and emergency_idx != main_idx:
        exit_coord = entrance_coords[emergency_idx]
        spine = _build_through_spine(entrance, exit_coord, usable_poly, G, nodes)
        if spine:
            return spine

    # 단일 입구: 입구 → deep wall center
    spine = _build_main_spine(entrance, usable_poly, G, nodes)
    return spine


def _build_through_spine(
    entrance: tuple[float, float],
    exit_coord: tuple[float, float],
    usable_poly: Polygon,
    G: nx.Graph,
    nodes: dict,
) -> LineString | None:
    """
    복수 입구 관통 동선: MAIN → deep wall 경유점 → EMERGENCY.
    deep wall = 두 입구 모두에서 가장 먼 벽면 중앙.
    """
    minx, miny, maxx, maxy = usable_poly.bounds
    cx = (minx + maxx) / 2
    cy = (miny + maxy) / 2
    ex, ey = entrance
    xx, xy = exit_coord

    # 두 입구의 중간점에서 가장 먼 벽면 = deep wall
    mid = ((ex + xx) / 2, (ey + xy) / 2)
    deep_wall = _find_deepest_wall_center(mid, usable_poly)
    dx, dy = deep_wall

    # 입구 → deep wall 경유점
    wp1 = _plan_rectilinear_waypoints(ex, ey, dx, dy, cx, cy,
                                       minx, miny, maxx, maxy)
    # deep wall → 출구 경유점
    wp2 = _plan_rectilinear_waypoints(dx, dy, xx, xy, cx, cy,
                                       minx, miny, maxx, maxy)
    # 병합 (deep wall 중복 제거)
    waypoints = wp1 + wp2[1:]

    spine_coords = _connect_waypoints_via_grid(waypoints, G, nodes)
    if len(spine_coords) >= 2:
        spine = LineString(spine_coords)
        print(f"[Agent2] Main Spine (through): {len(waypoints)} waypoints, "
              f"{len(spine_coords)} grid nodes, length={spine.length:.0f}mm")
        print(f"[Agent2] Main Spine: MAIN({ex:.0f},{ey:.0f}) → "
              f"deep({dx:.0f},{dy:.0f}) → EXIT({xx:.0f},{xy:.0f})")
        return spine

    return None


def _build_main_spine(
    entrance: tuple[float, float],
    usable_poly: Polygon,
    G: nx.Graph,
    nodes: dict,
) -> LineString:
    """
    입구 → 바닥 중심 → 최원 벽면 중앙을 직각 경유하는 Main Spine 생성.
    """
    ex, ey = entrance
    minx, miny, maxx, maxy = usable_poly.bounds
    cx = (minx + maxx) / 2
    cy = (miny + maxy) / 2

    # ── 1) 입구에서 가장 먼 벽면 edge → 중앙점 ─────────────────────────
    deep_wall_center = _find_deepest_wall_center(entrance, usable_poly)
    dx, dy = deep_wall_center

    # ── 2) 직각 경유점 결정 ─────────────────────────────────────────────
    # 입구와 종점의 관계에 따라 ㄱ자 또는 직진 경로 선택.
    # 원칙: 먼저 바닥 중심선까지 직진, 그 후 종점으로 직진 (최대 1회 꺾임).
    waypoints = _plan_rectilinear_waypoints(ex, ey, dx, dy, cx, cy,
                                             minx, miny, maxx, maxy)

    # ── 3) 각 구간을 그리드 노드로 연결 ─────────────────────────────────
    spine_coords = _connect_waypoints_via_grid(waypoints, G, nodes)

    if len(spine_coords) >= 2:
        spine = LineString(spine_coords)
        print(f"[Agent2] Main Spine: {len(waypoints)} waypoints, "
              f"{len(spine_coords)} grid nodes, length={spine.length:.0f}mm")
        print(f"[Agent2] Main Spine: entrance=({ex:.0f},{ey:.0f}) → "
              f"deep_wall=({dx:.0f},{dy:.0f})")
        return spine

    # fallback: 직선
    print(f"[Agent2] Main Spine: grid connection failed, straight fallback")
    return LineString([entrance, deep_wall_center])


def _find_deepest_wall_center(
    entrance: tuple[float, float],
    usable_poly: Polygon,
) -> tuple[float, float]:
    """입구에서 가장 먼 벽면 edge의 중앙점 반환."""
    coords = list(usable_poly.exterior.coords)
    entrance_pt = Point(entrance)

    best_edge_center = None
    best_dist = -1

    for i in range(len(coords) - 1):
        edge = LineString([coords[i], coords[i + 1]])
        if edge.length < 100:  # 극소 edge 무시
            continue
        edge_center = edge.interpolate(0.5, normalized=True)
        dist = entrance_pt.distance(edge_center)
        if dist > best_dist:
            best_dist = dist
            best_edge_center = (edge_center.x, edge_center.y)

    if best_edge_center is None:
        # fallback: centroid 반대편
        cx, cy = usable_poly.centroid.x, usable_poly.centroid.y
        return (2 * cx - entrance[0], 2 * cy - entrance[1])

    return best_edge_center


def _plan_rectilinear_waypoints(
    ex: float, ey: float,
    dx: float, dy: float,
    cx: float, cy: float,
    minx: float, miny: float, maxx: float, maxy: float,
) -> list[tuple[float, float]]:
    """
    입구(ex,ey) → 종점(dx,dy)을 직각 경로로 연결하는 경유점 리스트.

    입구가 어느 변에 있는지 판별하여 최적 경유 방향 결정.
    - 상/하 변 입구: 먼저 수직 직진(중심선까지) → 수평 이동 → 수직 직진(종점)
    - 좌/우 변 입구: 먼저 수평 직진(중심선까지) → 수직 이동 → 수평 직진(종점)
    직진 가능하면 경유점 없이 직선.
    """
    width = maxx - minx
    height = maxy - miny
    margin = min(width, height) * 0.05  # 벽과 edge 판별 마진

    # 입구가 어느 변에 있는지 판별
    on_top = abs(ey - miny) < margin
    on_bottom = abs(ey - maxy) < margin
    on_left = abs(ex - minx) < margin
    on_right = abs(ex - maxx) < margin

    waypoints = [(ex, ey)]

    # X축 또는 Y축이 이미 정렬되어 있으면 직진
    x_aligned = abs(ex - dx) < min(width, height) * 0.15
    y_aligned = abs(ey - dy) < min(width, height) * 0.15

    if x_aligned:
        # X가 비슷 → 수직 직진
        waypoints.append((ex, dy))
    elif y_aligned:
        # Y가 비슷 → 수평 직진
        waypoints.append((dx, ey))
    elif on_top or on_bottom:
        # 상/하 변 입구 → 먼저 수직으로 중심까지, 그 후 수평+수직
        waypoints.append((ex, cy))   # 수직 직진 → 중심 Y
        waypoints.append((dx, cy))   # 수평 이동 → 종점 X
        waypoints.append((dx, dy))   # 수직 직진 → 종점
    elif on_left or on_right:
        # 좌/우 변 입구 → 먼저 수평으로 중심까지, 그 후 수직+수평
        waypoints.append((cx, ey))   # 수평 직진 → 중심 X
        waypoints.append((cx, dy))   # 수직 이동 → 종점 Y
        waypoints.append((dx, dy))   # 수평 직진 → 종점
    else:
        # 판별 불가 → ㄱ자 (수직 먼저)
        waypoints.append((ex, dy))
        waypoints.append((dx, dy))

    # 종점이 마지막에 없으면 추가
    last = waypoints[-1]
    if abs(last[0] - dx) > 1 or abs(last[1] - dy) > 1:
        waypoints.append((dx, dy))

    # 중복 제거
    deduped = [waypoints[0]]
    for wp in waypoints[1:]:
        prev = deduped[-1]
        if abs(wp[0] - prev[0]) > 1 or abs(wp[1] - prev[1]) > 1:
            deduped.append(wp)

    return deduped


def _connect_waypoints_via_grid(
    waypoints: list[tuple[float, float]],
    G: nx.Graph,
    nodes: dict,
) -> list[tuple[float, float]]:
    """
    경유점 리스트를 그리드 노드로 연결.
    각 구간을 축 정렬 우선 Dijkstra로 연결하여 직각 경로 유지.
    """
    if len(waypoints) < 2:
        return waypoints

    all_coords: list[tuple[float, float]] = []

    for seg_i in range(len(waypoints) - 1):
        start_wp = waypoints[seg_i]
        end_wp = waypoints[seg_i + 1]

        start_node = nearest_node(nodes, start_wp)
        end_node = nearest_node(nodes, end_wp)

        if start_node == end_node:
            if not all_coords:
                all_coords.append(nodes[start_node])
            continue

        try:
            path = nx.shortest_path(G, start_node, end_node, weight="weight")
            segment_coords = [nodes[n] for n in path]

            # 이전 구간 끝과 현재 구간 시작이 같으면 중복 제거
            if all_coords and segment_coords:
                if (abs(all_coords[-1][0] - segment_coords[0][0]) < 1 and
                        abs(all_coords[-1][1] - segment_coords[0][1]) < 1):
                    segment_coords = segment_coords[1:]

            all_coords.extend(segment_coords)
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            # 연결 실패 시 직선 보간
            if not all_coords:
                all_coords.append(start_wp)
            all_coords.append(end_wp)

    return all_coords


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
