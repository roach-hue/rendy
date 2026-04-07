"""
Agent 2 후반부 — Facade (순수 조립, LLM 없음)

입력: ParsedDrawings + scale_mm_per_px
출력: space_data dict

5개 모듈을 순서대로 호출하여 조립:
  1. dead_zone_generator   — Dead Zone + inner walls
  2. slot_generator        — 외벽 slot + 내부 slot
  3. corridor_graph        — Choke Point 탐지
  4. walk_mm_calculator    — walk_mm + zone + Main Artery + Semantic Tag + Virtual Entrance
  5. agent2_summary        — Agent 3용 자연어 요약
"""
from shapely.geometry import LineString, Point, Polygon
from shapely.ops import unary_union

from app.schemas.drawings import DetectedEntrance, ParsedDrawings
from app.schemas.space_data import make_empty_space_data
from app.agents.dead_zone_generator import generate_dead_zones
from app.agents.slot_generator import generate_edge_slots, generate_interior_slots, max_object_width
from app.agents.corridor_graph import detect_choke_points
from app.agents.walk_mm_calculator import assign_walk_mm, assign_semantic_tags, build_virtual_entrance
from app.agents.agent2_summary import make_agent3_summary


def _snap_point_to_polygon(
    pt: tuple[float, float],
    poly: Polygon,
) -> tuple[float, float]:
    """
    좌표가 polygon 외부이면 가장 가까운 외벽 edge 위로 스냅.
    내부이면 그대로 반환.
    """
    p = Point(pt)
    if poly.contains(p) or poly.boundary.distance(p) < 1.0:
        return pt
    nearest = poly.exterior.interpolate(poly.exterior.project(p))
    snapped = (round(nearest.x, 1), round(nearest.y, 1))
    print(f"[Agent2] entrance snap: ({pt[0]:.0f},{pt[1]:.0f}) → ({snapped[0]:.0f},{snapped[1]:.0f})")
    return snapped


def _snap_entrances(
    entrances: list[DetectedEntrance],
    poly: Polygon,
    s: float,
    ox: float,
    oy: float,
) -> list[DetectedEntrance]:
    """복수 입구 좌표를 mm 변환 후 polygon 외부이면 스냅."""
    result = []
    for ent in entrances:
        mm_x = ent.x_px * s - ox
        mm_y = ent.y_px * s - oy
        snapped = _snap_point_to_polygon((mm_x, mm_y), poly)
        # 스냅된 좌표로 새 DetectedEntrance 생성 (px 단위로 역변환)
        result.append(DetectedEntrance(
            x_px=round((snapped[0] + ox) / s, 1),
            y_px=round((snapped[1] + oy) / s, 1),
            confidence=ent.confidence,
            is_main=ent.is_main,
            type=ent.type,
        ))
    return result


def run(
    drawings: ParsedDrawings,
    scale_mm_per_px: float,
    user_entrance_px: tuple[float, float] | None = None,
) -> dict:
    """Agent 2 후반부 메인 진입점 (Facade)."""
    fp = drawings.floor_plan
    space_data = make_empty_space_data()
    s = scale_mm_per_px

    # ── Step 1: 픽셀 → mm 변환 + 원점 정규화 ──────────────────────────────────
    floor_pts_mm_raw = [(x * s, y * s) for x, y in fp.floor_polygon_px]
    ox = min(p[0] for p in floor_pts_mm_raw)
    oy = min(p[1] for p in floor_pts_mm_raw)
    print(f"[Agent2] origin offset: ({ox:.0f}, {oy:.0f})mm")

    floor_pts_mm = [(x - ox, y - oy) for x, y in floor_pts_mm_raw]
    floor_poly = Polygon(floor_pts_mm)
    space_data["_origin_offset_mm"] = (round(ox, 1), round(oy, 1))

    inaccessible_polys = [
        Polygon([(x * s - ox, y * s - oy) for x, y in room.polygon_px])
        for room in fp.inaccessible_rooms
    ]

    # ── Step 1.5: 입구 좌표 스냅 (polygon 외부 → 최근접 edge) ────────────────
    if fp.entrances:
        fp_entrances_snapped = _snap_entrances(fp.entrances, floor_poly, s, ox, oy)
    else:
        fp_entrances_snapped = []

    entrance_mm = None
    if user_entrance_px:
        raw = (user_entrance_px[0] * s - ox, user_entrance_px[1] * s - oy)
        entrance_mm = _snap_point_to_polygon(raw, floor_poly)
    elif fp.entrance:
        raw = (fp.entrance.x_px * s - ox, fp.entrance.y_px * s - oy)
        entrance_mm = _snap_point_to_polygon(raw, floor_poly)
    elif fp_entrances_snapped:
        # entrances 리스트에서 main 입구 사용
        main = next((e for e in fp_entrances_snapped if e.is_main), fp_entrances_snapped[0])
        entrance_mm = (main.x_px * s - ox, main.y_px * s - oy)

    sprinklers_mm = [(p.x_px * s - ox, p.y_px * s - oy) for p in fp.sprinklers]
    hydrants_mm = [(p.x_px * s - ox, p.y_px * s - oy) for p in fp.fire_hydrant]
    panels_mm = [(p.x_px * s - ox, p.y_px * s - oy) for p in fp.electrical_panel]

    # ── Step 2: 배치 불가 영역 차감 ───────────────────────────────────────
    usable_poly = floor_poly
    if inaccessible_polys:
        diff = floor_poly.difference(unary_union(inaccessible_polys))
        # MultiPolygon이면 가장 큰 조각 선택 (inaccessible이 polygon을 분할한 경우)
        if diff.geom_type == "MultiPolygon":
            usable_poly = max(diff.geoms, key=lambda g: g.area)
            print(f"[Agent2] MultiPolygon → largest: {usable_poly.area:.0f}mm² "
                  f"(of {len(list(diff.geoms))} pieces)")
        elif diff.geom_type == "Polygon" and not diff.is_empty:
            usable_poly = diff
        # GeometryCollection 등 예외 → 원본 유지

    space_data["floor"]["polygon"] = usable_poly
    space_data["floor"]["usable_area_sqm"] = round(usable_poly.area / 1_000_000, 2)
    space_data["floor"]["max_object_w_mm"] = max_object_width(usable_poly)

    if drawings.section and drawings.section.ceiling_height_mm:
        space_data["floor"]["ceiling_height_mm"] = {
            "value": drawings.section.ceiling_height_mm,
            "confidence": "high",
            "source": "section_drawing",
        }

    space_data["infra"]["disclaimer"] = ["electrical_panel"] if panels_mm else []

    # ── Step 3: Dead Zone + Inner Walls ───────────────────────────────────
    floor_px_xs = [p[0] for p in fp.floor_polygon_px]
    floor_px_ys = [p[1] for p in fp.floor_polygon_px]

    dead_zones, inner_wall_linestrings = generate_dead_zones(
        sprinklers_mm, hydrants_mm, panels_mm,
        inaccessible_polys, fp.inner_walls, usable_poly,
        s, ox, oy, min(floor_px_xs), min(floor_px_ys),
    )

    space_data["inner_wall_linestrings"] = inner_wall_linestrings
    space_data["dead_zones"] = dead_zones

    # 벽면 LineString 저장
    exterior_coords = list(usable_poly.exterior.coords)
    exterior_linestrings = [
        LineString([exterior_coords[i], exterior_coords[i + 1]])
        for i in range(len(exterior_coords) - 1)
        if LineString([exterior_coords[i], exterior_coords[i + 1]]).length > 0
    ]
    space_data["exterior_wall_linestrings"] = exterior_linestrings
    space_data["all_wall_linestrings"] = exterior_linestrings + inner_wall_linestrings

    # ── Step 4: Slot 생성 (전이 지대 적용) ──────────────────────────────────
    slots = generate_edge_slots(usable_poly, dead_zones, entrances=fp_entrances_snapped or None)
    edge_count = len(slots)
    interior_slots = generate_interior_slots(
        usable_poly, dead_zones, inner_wall_linestrings,
        entrances=fp_entrances_snapped or None,
    )
    slots.update(interior_slots)
    print(f"[Agent2] slots: {edge_count} edge + {len(interior_slots)} interior = {len(slots)} total")

    # ── Step 4.7: Choke Point 탐지 ───────────────────────────────────────
    choke_points = detect_choke_points(
        usable_poly, dead_zones,
        space_data.get("all_wall_linestrings", []),
    )
    if choke_points:
        dead_zones.extend(choke_points)
        space_data["dead_zones"] = dead_zones
        print(f"[Agent2] choke points: {len(choke_points)} detected → dead zones 추가")
    space_data["choke_points"] = choke_points

    # ── Step 5: walk_mm + zone + Main Artery (복수 입구 대응) ────────────
    # all_entrances: mm 정규화 좌표 + type 튜플로 변환
    entrances_mm_for_walk = None
    if fp_entrances_snapped:
        entrances_mm_for_walk = [
            {"coord": (e.x_px * s - ox, e.y_px * s - oy), "type": e.type}
            for e in fp_entrances_snapped
        ]

    # 모든 입구 좌표를 space_data에 저장 (3D 시각화용)
    all_entrance_coords_mm = []
    if entrance_mm:
        all_entrance_coords_mm.append(entrance_mm)
    if entrances_mm_for_walk:
        for ent in entrances_mm_for_walk:
            coord = ent["coord"]
            # 주출입구와 동일 위치 중복 제거
            if all_entrance_coords_mm and (
                abs(coord[0] - all_entrance_coords_mm[0][0]) < 100 and
                abs(coord[1] - all_entrance_coords_mm[0][1]) < 100
            ):
                continue
            all_entrance_coords_mm.append(coord)
    space_data["_entrance_coords_mm"] = all_entrance_coords_mm

    if entrance_mm:
        main_artery = assign_walk_mm(
            slots, entrance_mm, usable_poly, dead_zones,
            all_entrances=entrances_mm_for_walk,
        )
        if main_artery:
            space_data["fire"]["main_artery"] = main_artery
    else:
        for slot in slots.values():
            slot["walk_mm"] = 0.0
            slot["zone_label"] = "entrance_zone"

    # ── Step 5.5: Semantic Tag ────────────────────────────────────────────
    assign_semantic_tags(slots, usable_poly, entrance_mm)

    # ── Step 6: Spine 거리 메타데이터 부여 ────────────────────────────────
    main_artery = space_data.get("fire", {}).get("main_artery")
    if main_artery:
        _assign_spine_proximity(slots, main_artery)

    for key, slot in slots.items():
        space_data[key] = slot

    # ── Step 6.5: Virtual Entrance (복수 입구 대응) ─────────────────────
    entrance_width = fp.entrance_width_mm or 2000.0
    all_entrance_buffers = []

    if entrance_mm:
        entrance_line, entrance_buffer = build_virtual_entrance(
            entrance_mm, usable_poly, entrance_width
        )
        space_data["entrance_line"] = entrance_line
        space_data["entrance_buffer"] = entrance_buffer
        all_entrance_buffers.append(entrance_buffer)

    # 추가 입구 buffer 생성 (EMERGENCY_EXIT 등)
    if entrances_mm_for_walk:
        for ent in entrances_mm_for_walk:
            coord = ent["coord"]
            if entrance_mm and (abs(coord[0] - entrance_mm[0]) < 100 and
                                abs(coord[1] - entrance_mm[1]) < 100):
                continue  # 주출입구와 동일 위치 → 중복 skip
            _, extra_buffer = build_virtual_entrance(coord, usable_poly, entrance_width)
            all_entrance_buffers.append(extra_buffer)

    # 모든 입구 buffer 병합 → placement_engine static_cache용
    if len(all_entrance_buffers) > 1:
        space_data["entrance_buffer"] = unary_union(all_entrance_buffers)

    print(f"[Agent2] virtual entrance: {len(all_entrance_buffers)} entrances, "
          f"width={entrance_width}mm")

    # ── Step 7: Agent 3용 자연어 요약 ─────────────────────────────────────
    space_data["_agent3_summary"] = make_agent3_summary(slots, space_data)

    return space_data


def _assign_spine_proximity(
    slots: dict[str, dict],
    main_artery: LineString,
) -> None:
    """
    각 슬롯에 주동선(Spine) 거리 기반 메타데이터 부여.

    추가 필드:
    - spine_dist_mm: 슬롯과 Spine 사이 최단 거리 (mm)
    - spine_rank: "adjacent" (2m 이내) | "nearby" (5m 이내) | "far"
    """
    for slot in slots.values():
        pt = Point(slot["x_mm"], slot["y_mm"])
        dist = main_artery.distance(pt)
        slot["spine_dist_mm"] = round(dist)

        if dist <= 2000:
            slot["spine_rank"] = "adjacent"
        elif dist <= 5000:
            slot["spine_rank"] = "nearby"
        else:
            slot["spine_rank"] = "far"

    counts = {"adjacent": 0, "nearby": 0, "far": 0}
    for slot in slots.values():
        counts[slot.get("spine_rank", "far")] += 1
    print(f"[Agent2] spine proximity: adjacent={counts['adjacent']}, "
          f"nearby={counts['nearby']}, far={counts['far']}")
