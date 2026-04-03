"""
Agent 2 후반부 — 공간 연산 모듈 (순수 코드, LLM 없음)

입력: ParsedDrawings + 사용자 마킹 확정 데이터 + scale_mm_per_px
출력: space_data dict (placement_slot, zone_label, walk_mm, Dead Zone 포함)

처리 순서:
  1. 픽셀 → mm 변환
  2. floor_polygon에서 inaccessible_rooms 차감
  3. Dead Zone 생성 (설비 주변 buffer)
  4. placement_slot + wall_linestring + wall_normal 계산
  5. NetworkX 격자 그래프 + walk_mm + zone_label 부여
  6. Main Artery LineString 캐싱
  7. Agent 3용 자연어 요약 생성
"""
import math
from typing import Any

import networkx as nx
from shapely.geometry import LineString, MultiPolygon, Point, Polygon
from shapely.ops import unary_union

from app.schemas.drawings import ParsedDrawings
from app.schemas.space_data import assign_zone_by_walk_mm, make_empty_space_data

# Dead Zone buffer 반경 (mm)
DEAD_ZONE_BUFFER = {
    "sprinkler": 300,
    "fire_hydrant": 500,
    "electrical_panel": 600,
}

# Inner Wall 양쪽 buffer (mm) — 추후 수정 용이하도록 상수 분리
INNER_WALL_BUFFER_MM = 150

# NetworkX 격자 step (mm)
GRID_STEP_MM = 500


def run(
    drawings: ParsedDrawings,
    scale_mm_per_px: float,
    user_entrance_px: tuple[float, float] | None = None,
) -> dict:
    """
    Agent 2 후반부 메인 진입점.
    user_entrance_px: 마킹 UI에서 사용자가 확정한 입구 좌표 (픽셀).
                      None이면 Vision 감지 결과 사용.
    """
    fp = drawings.floor_plan
    space_data = make_empty_space_data()

    # ── Step 1: 픽셀 → mm 변환 + 원점 정규화 ──────────────────────────────────
    s = scale_mm_per_px

    floor_pts_mm_raw = [(x * s, y * s) for x, y in fp.floor_polygon_px]
    # 원점(0,0)으로 정규화: polygon 최소 좌표를 원점으로 이동
    ox = min(p[0] for p in floor_pts_mm_raw)
    oy = min(p[1] for p in floor_pts_mm_raw)
    print(f"[Agent2] origin offset: ({ox:.0f}, {oy:.0f})mm")

    floor_pts_mm = [(x - ox, y - oy) for x, y in floor_pts_mm_raw]
    floor_poly = Polygon(floor_pts_mm)

    # 원점 offset 저장 — 프론트에서 mm→px 역변환 시 필요
    space_data["_origin_offset_mm"] = (round(ox, 1), round(oy, 1))

    inaccessible_polys = [
        Polygon([(x * s - ox, y * s - oy) for x, y in room.polygon_px])
        for room in fp.inaccessible_rooms
    ]

    entrance_mm: tuple[float, float] | None = None
    if user_entrance_px:
        entrance_mm = (user_entrance_px[0] * s - ox, user_entrance_px[1] * s - oy)
    elif fp.entrance:
        entrance_mm = (fp.entrance.x_px * s - ox, fp.entrance.y_px * s - oy)

    sprinklers_mm = [(p.x_px * s - ox, p.y_px * s - oy) for p in fp.sprinklers]
    hydrants_mm   = [(p.x_px * s - ox, p.y_px * s - oy) for p in fp.fire_hydrant]
    panels_mm     = [(p.x_px * s - ox, p.y_px * s - oy) for p in fp.electrical_panel]

    # ── Step 2: 배치 불가 영역 차감 ───────────────────────────────────────
    usable_poly = floor_poly
    if inaccessible_polys:
        usable_poly = floor_poly.difference(unary_union(inaccessible_polys))

    space_data["floor"]["polygon"] = usable_poly
    space_data["floor"]["usable_area_sqm"] = round(usable_poly.area / 1_000_000, 2)
    space_data["floor"]["max_object_w_mm"] = _max_object_width(usable_poly)

    # ceiling_height_mm: 단면도 추출 or DEFAULTS 적용
    if drawings.section and drawings.section.ceiling_height_mm:
        space_data["floor"]["ceiling_height_mm"] = {
            "value": drawings.section.ceiling_height_mm,
            "confidence": "high",
            "source": "section_drawing",
        }
    # else: DEFAULTS에서 3000mm가 이미 적용됨

    # ── Step 3: Dead Zone 생성 ─────────────────────────────────────────────
    dead_zones = []
    for pt in sprinklers_mm:
        dead_zones.append(Point(pt).buffer(DEAD_ZONE_BUFFER["sprinkler"]))
    for pt in hydrants_mm:
        dead_zones.append(Point(pt).buffer(DEAD_ZONE_BUFFER["fire_hydrant"]))
    for pt in panels_mm:
        dead_zones.append(Point(pt).buffer(DEAD_ZONE_BUFFER["electrical_panel"]))

    space_data["infra"]["disclaimer"] = (
        ["electrical_panel"] if panels_mm else []
    )

    # ── Step 3.5a: Inaccessible Rooms → Dead Zone 추가 ──────────────────
    for room_poly in inaccessible_polys:
        if room_poly.is_valid and room_poly.area > 0:
            dead_zones.append(room_poly)
    if inaccessible_polys:
        print(f"[Agent2] inaccessible rooms: {len(inaccessible_polys)} → dead zones")

    # ── Step 3.5b: Inner Walls → LineString 정비 + Dead Zone 변환 ───────────
    # Vision이 inner_walls를 floor polygon 내부 로컬 좌표로 반환하는 경우 보정
    # floor polygon px의 최소점을 기준 원점으로 사용
    floor_px_xs = [p[0] for p in fp.floor_polygon_px]
    floor_px_ys = [p[1] for p in fp.floor_polygon_px]
    floor_px_min_x = min(floor_px_xs)
    floor_px_min_y = min(floor_px_ys)

    inner_wall_linestrings: list[LineString] = []
    for wall in fp.inner_walls:
        wx0, wy0 = wall.start_px
        wx1, wy1 = wall.end_px
        # inner_walls가 floor polygon 범위 밖이면 로컬 좌표로 판단 → floor 원점 보정
        if wx0 < floor_px_min_x * 0.8 or wy0 < floor_px_min_y * 0.8:
            wx0 += floor_px_min_x
            wy0 += floor_px_min_y
            wx1 += floor_px_min_x
            wy1 += floor_px_min_y
        wall_ls = LineString([
            (wx0 * s - ox, wy0 * s - oy),
            (wx1 * s - ox, wy1 * s - oy),
        ])
        if wall_ls.length > 0:
            # floor polygon 내부 부분만 클리핑
            clipped = usable_poly.intersection(wall_ls)
            if not clipped.is_empty and clipped.length > 0:
                # MultiLineString이면 가장 긴 것 선택
                if clipped.geom_type == "MultiLineString":
                    clipped = max(clipped.geoms, key=lambda g: g.length)
                if clipped.geom_type == "LineString" and clipped.length > 10:
                    inner_wall_linestrings.append(clipped)
                    dead_zones.append(clipped.buffer(INNER_WALL_BUFFER_MM))

    # 외벽과 동일한 LineString 리스트로 space_data에 저장
    space_data["inner_wall_linestrings"] = inner_wall_linestrings
    if inner_wall_linestrings:
        print(f"[Agent2] inner walls: {len(inner_wall_linestrings)} LineStrings saved, "
              f"dead zones +{len(inner_wall_linestrings)} (buffer={INNER_WALL_BUFFER_MM}mm)")

    space_data["dead_zones"] = dead_zones

    # 외벽 LineString 리스트 저장 (내벽과 동일 자료형)
    exterior_coords = list(usable_poly.exterior.coords)
    exterior_linestrings: list[LineString] = []
    for i in range(len(exterior_coords) - 1):
        seg = LineString([exterior_coords[i], exterior_coords[i + 1]])
        if seg.length > 0:
            exterior_linestrings.append(seg)
    space_data["exterior_wall_linestrings"] = exterior_linestrings
    # 전체 벽면 = 외벽 + 내벽 (통합 기하학 연산용)
    space_data["all_wall_linestrings"] = exterior_linestrings + inner_wall_linestrings

    # ── Step 4: placement_slot 생성 (외벽) ──────────────────────────────────
    slots = _generate_placement_slots(usable_poly, dead_zones)
    edge_count = len(slots)

    # ── Step 4.5: 내부 slot 생성 (interior_slot) ─────────────────────────
    interior_slots = _generate_interior_slots(usable_poly, dead_zones, inner_wall_linestrings)
    slots.update(interior_slots)
    print(f"[Agent2] slots: {edge_count} edge + {len(interior_slots)} interior = {len(slots)} total")

    # ── Step 4.7: Choke Point 병목 구역 탐지 ─────────────────────────────
    choke_points = _detect_choke_points(
        usable_poly, dead_zones,
        space_data.get("all_wall_linestrings", []),
    )
    if choke_points:
        dead_zones.extend(choke_points)
        space_data["dead_zones"] = dead_zones  # 갱신
        print(f"[Agent2] choke points: {len(choke_points)} detected → dead zones 추가")
    space_data["choke_points"] = choke_points

    # ── Step 5: NetworkX 격자 + walk_mm + zone_label + Main Artery ────────
    if entrance_mm:
        main_artery = _assign_walk_mm(slots, entrance_mm, usable_poly, dead_zones)
        if main_artery:
            space_data["fire"]["main_artery"] = main_artery
    else:
        for slot in slots.values():
            slot["walk_mm"] = 0.0
            slot["zone_label"] = "entrance_zone"

    # ── Step 5.5: Semantic Tag 부여 ─────────────────────────────────────
    _assign_semantic_tags(slots, usable_poly, entrance_mm)

    for key, slot in slots.items():
        space_data[key] = slot

    # ── Step 6.5: Virtual Entrance 생성 ─────────────────────────────────
    if entrance_mm:
        entrance_width = fp.entrance_width_mm or 2000.0  # 파서 추출 or 기본값
        entrance_line, entrance_buffer = _build_virtual_entrance(
            entrance_mm, usable_poly, entrance_width
        )
        space_data["entrance_line"] = entrance_line
        space_data["entrance_buffer"] = entrance_buffer
        print(f"[Agent2] virtual entrance: width={entrance_width}mm, "
              f"buffer area={entrance_buffer.area:.0f}mm²")

    # ── Step 7: Agent 3용 자연어 요약 ─────────────────────────────────────
    space_data["_agent3_summary"] = _make_agent3_summary(slots, space_data)

    return space_data


# ── 내부 헬퍼 ──────────────────────────────────────────────────────────────

def _max_object_width(poly: Polygon) -> float:
    """usable polygon 내 배치 가능한 최대 오브젝트 너비 (mm). bbox 단변의 40%."""
    minx, miny, maxx, maxy = poly.bounds
    short_side = min(maxx - minx, maxy - miny)
    return round(short_side * 0.4)


def _generate_placement_slots(
    usable_poly: Polygon,
    dead_zones: list,
) -> dict[str, dict]:
    """
    벽면을 따라 placement_slot 생성.
    외벽의 각 변을 step_mm 간격으로 샘플링 → 중심점 후보 → Dead Zone 제외.
    """
    coords = list(usable_poly.exterior.coords)
    slots: dict[str, dict] = {}

    # step_mm 동적 계산: 설계 기준 sqrt(w²+d²) × ratio
    # slot 생성 시점에는 개별 오브젝트 크기를 모르므로,
    # max_object_w_mm (공간 단변의 40%) 기준으로 대각선 추정
    max_w = _max_object_width(usable_poly)
    step_mm = max(500, min(2000, int(math.sqrt(max_w**2 + max_w**2) * 0.7)))

    print(f"[Agent2] polygon vertices: {len(coords)-1}, bounds: {usable_poly.bounds}, "
          f"step_mm={step_mm} (max_object_w={max_w}mm)")

    for i in range(len(coords) - 1):
        p1 = coords[i]
        p2 = coords[i + 1]
        seg = LineString([p1, p2])
        seg_len = seg.length
        if seg_len < step_mm:
            print(f"[Agent2] wall {i}: ({p1[0]:.0f},{p1[1]:.0f})→({p2[0]:.0f},{p2[1]:.0f}) len={seg_len:.0f}mm < {step_mm}mm, skip")
            continue

        # 벽 법선 방향 계산 (내부 방향)
        dx = p2[0] - p1[0]
        dy = p2[1] - p1[1]
        length = math.hypot(dx, dy)
        # 90도 회전 (내부 방향 결정은 centroid 기준)
        nx_dir = -dy / length
        ny_dir =  dx / length
        centroid = usable_poly.centroid
        mid = ((p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2)
        # 내부 방향 확인
        test = Point(mid[0] + nx_dir * 100, mid[1] + ny_dir * 100)
        if not usable_poly.contains(test):
            nx_dir, ny_dir = -nx_dir, -ny_dir

        wall_name = _wall_direction_name(dx, dy)

        # step 간격으로 슬롯 샘플링
        n_steps = int(seg_len / step_mm)
        for j in range(1, n_steps):
            t = j / n_steps
            x = p1[0] + t * (p2[0] - p1[0])
            y = p1[1] + t * (p2[1] - p1[1])
            pt = Point(x, y)

            # Dead Zone 내부면 제외
            in_dead = any(dz.contains(pt) for dz in dead_zones)
            if in_dead:
                continue

            slot_key = f"{wall_name}_slot_{i}_{j}"
            slots[slot_key] = {
                "x_mm": round(x),
                "y_mm": round(y),
                "wall_linestring": seg,
                "wall_normal": _normal_label(nx_dir, ny_dir),
                "zone_label": "entrance_zone",   # walk_mm 계산 전 임시
                "shelf_capacity": _shelf_capacity(seg_len),
                "walk_mm": 0.0,
            }
            print(f"[Agent2] slot {slot_key}: ({round(x)},{round(y)})mm, "
                  f"wall={wall_name}, normal={_normal_label(nx_dir, ny_dir)}, "
                  f"seg_len={seg_len:.0f}mm")

    return slots


# 병목 탐지 buffer 반경 (mm)
CHOKE_BUFFER_MM = 450


def _detect_choke_points(
    usable_poly: Polygon,
    dead_zones: list,
    all_walls: list[LineString],
) -> list[Polygon]:
    """
    병목 구역(Choke Point) 탐지.

    전략:
    1. 원본 장애물(벽면 LineString + dead_zone)을 수집
    2. pairwise 최단 거리가 900mm 미만인 쌍만 선별 (실제 병목)
    3. 해당 쌍의 buffer(450) 교집합 = choke 영역
    4. usable_poly 내부만 채택
    """
    # 원본 장애물 geometry 수집 (buffer 전)
    raw_obstacles = []
    for wall in all_walls:
        if wall.length > 0:
            raw_obstacles.append(wall)
    for dz in dead_zones:
        if hasattr(dz, "boundary") and not dz.is_empty:
            raw_obstacles.append(dz)

    choke_points: list[Polygon] = []

    # pairwise: 두 장애물 간 최단 거리 < 900mm인 쌍만 → buffer 교집합
    for i in range(len(raw_obstacles)):
        for j in range(i + 1, len(raw_obstacles)):
            try:
                gap = raw_obstacles[i].distance(raw_obstacles[j])
                # 900mm 미만이면 진짜 병목 (이미 접하는 경우는 gap=0 → 교차)
                if gap >= 900 or gap <= 0:
                    continue

                # 양쪽 buffer(450)의 교집합 = 통로가 좁아지는 영역
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

    # 중복 제거 + 면적 상한 필터 (공간 면적의 5% 이상이면 병목이 아닌 넓은 교차 → 제외)
    max_choke_area = usable_poly.area * 0.05
    if choke_points:
        from shapely.ops import unary_union
        merged = unary_union(choke_points)
        if merged.geom_type == "MultiPolygon":
            choke_points = [g for g in merged.geoms if 100 <= g.area <= max_choke_area]
        elif merged.geom_type == "Polygon" and 100 <= merged.area <= max_choke_area:
            choke_points = [merged]
        else:
            choke_points = []

    return choke_points


def _generate_interior_slots(
    usable_poly: Polygon,
    dead_zones: list,
    inner_walls: list[LineString],
) -> dict[str, dict]:
    """
    공간 내부 격자점에 interior_slot 생성.
    - usable_poly bbox 내부를 step_mm 격자로 순회
    - usable_poly.contains() + dead_zone 제외 + inner_wall buffer 제외
    - 외벽에서 충분히 떨어진 점만 (외벽 slot과 중복 방지)
    - 가장 가까운 벽면(외벽/내벽) 기준으로 wall_linestring/wall_normal 부여
    """
    max_w = _max_object_width(usable_poly)
    step_mm = max(500, min(2000, int(math.sqrt(max_w**2 + max_w**2) * 0.7)))
    # 내부 slot은 외벽에서 step_mm 이상 떨어진 점만 (외벽 slot 영역과 구분)
    min_wall_dist = step_mm * 0.8

    minx, miny, maxx, maxy = usable_poly.bounds
    slots: dict[str, dict] = {}

    # 내벽 buffer 장애물
    inner_wall_buffers = [w.buffer(INNER_WALL_BUFFER_MM) for w in inner_walls if w.length > 0]

    # 외벽 + 내벽 전체 리스트 (nearest wall 계산용)
    exterior_coords = list(usable_poly.exterior.coords)
    all_segments: list[LineString] = []
    for i in range(len(exterior_coords) - 1):
        seg = LineString([exterior_coords[i], exterior_coords[i + 1]])
        if seg.length > 0:
            all_segments.append(seg)
    all_segments.extend(inner_walls)

    ix = 0
    for gx in _frange(minx + step_mm, maxx - step_mm, step_mm):
        for gy in _frange(miny + step_mm, maxy - step_mm, step_mm):
            pt = Point(gx, gy)

            # usable_poly 내부만
            if not usable_poly.contains(pt):
                continue

            # 외벽에서 충분히 떨어져야 (외벽 slot과 중복 방지)
            if usable_poly.exterior.distance(pt) < min_wall_dist:
                continue

            # dead zone 내부 제외
            if any(dz.contains(pt) for dz in dead_zones):
                continue

            # inner wall buffer 내부 제외
            if any(wb.contains(pt) for wb in inner_wall_buffers):
                continue

            # 가장 가까운 벽면(외벽/내벽) 찾기 → wall_linestring + wall_normal
            nearest_seg = None
            nearest_dist = float("inf")
            for seg in all_segments:
                d = seg.distance(pt)
                if d < nearest_dist:
                    nearest_dist = d
                    nearest_seg = seg

            if nearest_seg:
                # 벽 법선: 벽 시작→끝 벡터의 90° 회전
                c0, c1 = nearest_seg.coords[0], nearest_seg.coords[1]
                dx = c1[0] - c0[0]
                dy = c1[1] - c0[1]
                seg_len = math.hypot(dx, dy)
                if seg_len > 0:
                    nx_dir = -dy / seg_len
                    ny_dir = dx / seg_len
                    # 내부 방향 확인
                    test = Point(gx + nx_dir * 100, gy + ny_dir * 100)
                    if not usable_poly.contains(test):
                        nx_dir, ny_dir = -nx_dir, -ny_dir
                    normal_label = _normal_label(nx_dir, ny_dir)
                else:
                    normal_label = "north"
                    nearest_seg = LineString([(gx, gy), (gx + 1, gy)])
            else:
                normal_label = "north"
                nearest_seg = LineString([(gx, gy), (gx + 1, gy)])

            slot_key = f"interior_slot_{ix}"
            slots[slot_key] = {
                "x_mm": round(gx),
                "y_mm": round(gy),
                "wall_linestring": nearest_seg,
                "wall_normal": normal_label,
                "zone_label": "entrance_zone",  # walk_mm 계산 전 임시
                "shelf_capacity": 1,
                "walk_mm": 0.0,
            }
            ix += 1

    return slots


def build_corridor_graph(
    usable_poly: Polygon,
    step_mm: float = GRID_STEP_MM,
    dead_zones: list | None = None,
) -> tuple[nx.Graph, dict[tuple[int, int], tuple[float, float]]]:
    """
    usable_poly 내부에 격자 그래프 생성.
    dead_zones 영역 내 노드는 소거 → 물리적 보행 불가 영역 반영.
    placement_engine에서 통로 연결성 검증에 재사용.
    Returns: (Graph, {node_key: (x_mm, y_mm)})
    """
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
            # Dead Zone 내부 노드 소거
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


def _assign_walk_mm(
    slots: dict[str, dict],
    entrance_mm: tuple[float, float],
    usable_poly: Polygon,
    dead_zones: list | None = None,
) -> LineString | None:
    """
    NetworkX 격자 그래프로 입구→각 슬롯 보행 거리(walk_mm) 계산 후 zone_label 부여.
    Main Artery를 Dijkstra 최단 경로(우회)로 생성하여 반환.
    그래프 객체는 이 함수 내에서만 사용 — space_data에 저장 금지.
    """
    G, nodes = build_corridor_graph(usable_poly, dead_zones=dead_zones)
    if not nodes:
        return None

    entrance_node = _nearest_node(nodes, entrance_mm)

    try:
        lengths = nx.single_source_dijkstra_path_length(
            G, entrance_node, weight="weight"
        )
    except nx.NetworkXError:
        return None

    minx, miny, maxx, maxy = usable_poly.bounds

    # 공간 크기 비례 zone 경계 — 최대 walk 거리 기준 33%/66% 분할
    max_walk = max(maxx - minx, maxy - miny)
    zone_1 = max_walk * 0.33
    zone_2 = max_walk * 0.66
    zones = {
        "entrance_zone": {"walk_mm_min": 0,       "walk_mm_max": zone_1},
        "mid_zone":      {"walk_mm_min": zone_1,  "walk_mm_max": zone_2},
        "deep_zone":     {"walk_mm_min": zone_2,  "walk_mm_max": float("inf")},
    }

    for slot in slots.values():
        slot_node = _nearest_node(nodes, (slot["x_mm"], slot["y_mm"]))
        walk = lengths.get(slot_node, float("inf"))
        # inf → 최대 walk 거리로 대체 (그래프 분리 시 도달 불가 slot)
        if walk == float("inf"):
            walk = max_walk * 2
        slot["walk_mm"] = round(walk)
        slot["zone_label"] = assign_zone_by_walk_mm(walk, zones)

    # Main Artery: Dijkstra 최단 경로 (직선 → 우회 경로)
    far_pt = _farthest_point(usable_poly, entrance_mm)
    far_node = _nearest_node(nodes, far_pt)
    try:
        path_nodes = nx.shortest_path(G, entrance_node, far_node, weight="weight")
        path_coords = [nodes[n] for n in path_nodes]
        if len(path_coords) >= 2:
            main_artery = LineString(path_coords)
            print(f"[Agent2] Main Artery: Dijkstra {len(path_coords)} nodes, "
                  f"length={main_artery.length:.0f}mm")
            return main_artery
    except (nx.NetworkXNoPath, nx.NodeNotFound):
        print("[Agent2] Main Artery: Dijkstra failed, fallback to straight line")

    # fallback: 직선
    return LineString([entrance_mm, far_pt])


def _assign_semantic_tags(
    slots: dict[str, dict],
    usable_poly: Polygon,
    entrance_mm: tuple[float, float] | None,
) -> None:
    """
    각 slot에 공간 특성 텍스트 태그 부여.
    - corner: 외벽 꼭짓점 500mm 이내 + 인접 2벽 각도 60~120°
    - wall_adjacent: 외벽 600mm 이내 (corner 아닌)
    - center_area: 모든 외벽에서 단변 30% 이상 떨어진
    - entrance_facing: walk_mm가 전체 최소의 150% 이내
    """
    coords = list(usable_poly.exterior.coords)
    minx, miny, maxx, maxy = usable_poly.bounds
    short_side = min(maxx - minx, maxy - miny)
    center_threshold = short_side * 0.3

    # 꼭짓점별 인접 벽 각도 계산
    corner_vertices = []
    for i in range(len(coords) - 1):
        prev_i = (i - 1) % (len(coords) - 1)
        next_i = (i + 1) % (len(coords) - 1)
        # 두 인접 벽의 방향 벡터
        dx1 = coords[i][0] - coords[prev_i][0]
        dy1 = coords[i][1] - coords[prev_i][1]
        dx2 = coords[next_i][0] - coords[i][0]
        dy2 = coords[next_i][1] - coords[i][1]
        len1 = math.hypot(dx1, dy1)
        len2 = math.hypot(dx2, dy2)
        if len1 > 0 and len2 > 0:
            cos_angle = (dx1 * dx2 + dy1 * dy2) / (len1 * len2)
            cos_angle = max(-1, min(1, cos_angle))  # clamp
            angle = math.degrees(math.acos(cos_angle))
            if 60 <= angle <= 120:
                corner_vertices.append(coords[i])

    # walk_mm 최소값
    min_walk = min((s["walk_mm"] for s in slots.values()), default=0)

    tagged_count = 0
    for slot in slots.values():
        tags: list[str] = []
        sx, sy = slot["x_mm"], slot["y_mm"]
        slot_pt = Point(sx, sy)

        # corner
        is_corner = any(
            math.hypot(sx - cx, sy - cy) < 500
            for cx, cy in corner_vertices
        )
        if is_corner:
            tags.append("corner")

        # wall_adjacent (corner 아닌 경우만)
        wall_dist = usable_poly.exterior.distance(slot_pt)
        if not is_corner and wall_dist < 600:
            tags.append("wall_adjacent")

        # center_area
        if wall_dist > center_threshold:
            tags.append("center_area")

        # entrance_facing
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


def _build_virtual_entrance(
    entrance_mm: tuple[float, float],
    usable_poly: Polygon,
    entrance_width: float,
) -> tuple[LineString, Polygon]:
    """
    입구 점 → 가장 가까운 외벽 edge 찾기 → ±width/2 구간의 LineString 생성
    → 법선 방향으로 offset하여 buffer Polygon 생성.
    """
    coords = list(usable_poly.exterior.coords)
    entrance_pt = Point(entrance_mm)

    # 가장 가까운 외벽 edge 찾기
    best_edge = None
    best_dist = float("inf")
    for i in range(len(coords) - 1):
        edge = LineString([coords[i], coords[i + 1]])
        dist = edge.distance(entrance_pt)
        if dist < best_dist:
            best_dist = dist
            best_edge = edge

    if not best_edge:
        # fallback: 입구 점 기준 수평 2000mm 선분
        half = entrance_width / 2
        line = LineString([
            (entrance_mm[0] - half, entrance_mm[1]),
            (entrance_mm[0] + half, entrance_mm[1]),
        ])
        return line, line.buffer(460)

    # edge 위에서 entrance 투영 → ±width/2 구간
    proj = best_edge.project(entrance_pt)
    half = entrance_width / 2
    start = max(0, proj - half)
    end = min(best_edge.length, proj + half)

    p_start = best_edge.interpolate(start)
    p_end = best_edge.interpolate(end)
    entrance_line = LineString([(p_start.x, p_start.y), (p_end.x, p_end.y)])

    # 법선 방향으로 460mm (450mm 통로 + 10mm 마진) offset
    # offset_curve: 양수=왼쪽, 내부 방향 확인 필요
    buffer_poly = entrance_line.buffer(460, single_sided=False)

    return entrance_line, buffer_poly


def _farthest_point(poly: Polygon, origin: tuple[float, float]) -> tuple[float, float]:
    """polygon 꼭짓점 중 origin에서 가장 먼 점 반환 (Main Artery 끝점)."""
    origin_pt = Point(origin)
    coords = list(poly.exterior.coords)
    return max(coords, key=lambda c: origin_pt.distance(Point(c)))


def _nearest_node(
    nodes: dict[tuple[int, int], tuple[float, float]],
    target: tuple[float, float],
) -> tuple[int, int]:
    """nodes 중 target에 가장 가까운 노드 키 반환."""
    return min(nodes.keys(), key=lambda k: math.hypot(
        nodes[k][0] - target[0], nodes[k][1] - target[1]
    ))


def _wall_direction_name(dx: float, dy: float) -> str:
    if abs(dx) > abs(dy):
        return "south_wall" if dy >= 0 else "north_wall"
    return "east_wall" if dx >= 0 else "west_wall"


def _normal_label(nx_dir: float, ny_dir: float) -> str:
    if abs(nx_dir) > abs(ny_dir):
        return "east" if nx_dir > 0 else "west"
    return "south" if ny_dir > 0 else "north"


def _shelf_capacity(wall_len_mm: float) -> int:
    """벽면 길이 기준 선반 수용 개수 추정 (1200mm당 1개)."""
    return max(1, int(wall_len_mm / 1200))


def _frange(start: float, stop: float, step: float) -> list[float]:
    result = []
    v = start
    while v <= stop:
        result.append(v)
        v += step
    return result


def _make_agent3_summary(slots: dict[str, dict], space_data: dict) -> str:
    """Agent 3 프롬프트용 자연어 요약 문자열 생성."""
    lines = [
        f"총 배치 가능 면적: {space_data['floor'].get('usable_area_sqm', '?')}m²",
        f"천장 높이: {space_data['floor'].get('ceiling_height_mm', {}).get('value', 3000)}mm",
        "",
        "배치 슬롯 목록:",
    ]
    for key, slot in slots.items():
        tags = slot.get("semantic_tags", [])
        tag_str = f", tags=[{', '.join(tags)}]" if tags else ""
        lines.append(
            f"  {key}: {slot['zone_label']}, "
            f"walk_mm={slot['walk_mm']}, "
            f"선반 수용={slot['shelf_capacity']}개"
            f"{tag_str}"
        )
    return "\n".join(lines)
