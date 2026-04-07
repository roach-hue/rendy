"""
P0-5b — 배치 엔진 (코드 순회 루프)

Agent 3의 Placement 결정 리스트를 받아 순서대로 배치 시도.
각 오브젝트마다:
  1. calculate_position으로 좌표 + bbox 생성
  2. Shapely 충돌 체크 (기배치 오브젝트, Dead Zone)
  3. buffer 이원화 체크 (Main Artery 600mm, 일반 통로 450mm)
  4. 관계 제약 검증 (distance < clearspace_mm)
  5. 충돌 시 step_mm 간격으로 대안 위치 탐색
  6. 성공 시 placed_objects에 추가

증분 검증: 오브젝트 단위 배치 즉시 검증. 일괄 검증 금지.
"""
from typing import Optional

import networkx as nx
from shapely.geometry import LineString, Point, Polygon

from app.schemas.placement import Placement
from app.modules.calculate_position import calculate_position
from app.agents.corridor_graph import nearest_node as _nearest_node

# spine_rank 정렬: 핵심 기물은 adjacent 우선, 벽면 기물은 far 우선
_SPINE_NEAR_FIRST = {"adjacent": 0, "nearby": 1, "far": 2}
_SPINE_FAR_FIRST = {"far": 0, "nearby": 1, "adjacent": 2}


def run_placement_loop(
    placements: list[Placement],
    eligible_objects: list[dict],
    space_data: dict,
    brand_data: dict,
    existing_placed: list[dict] | None = None,
) -> dict:
    """
    배치 엔진 메인 루프.

    Args:
        existing_placed: 이전 라운드에서 배치된 오브젝트 (bbox_polygon 포함).
                         retry/reset 시 기배치 충돌 방지용.

    Returns:
        {
            "placed": [배치 성공 오브젝트 dict],
            "failed": [배치 실패 오브젝트 dict],
            "log": [str],
        }
    """
    placed_polygons: list[dict] = list(existing_placed) if existing_placed else []
    failed: list[dict] = []
    log: list[str] = []

    # 오브젝트 타입 → eligible 매핑
    obj_map = {o["object_type"]: o for o in eligible_objects}

    # 공간 데이터
    floor_poly: Polygon = space_data.get("floor", {}).get("polygon")
    dead_zones: list = space_data.get("dead_zones", [])
    main_artery: Optional[LineString] = space_data.get("fire", {}).get("main_artery")
    clearspace_mm = _get_clearspace(brand_data)
    pair_rules = brand_data.get("object_pair_rules", [])

    # Static Cache: 정적 장애물 1회 Union 병합
    # 내벽, inaccessible, Dead Zone, Main Artery buffer → 루프에서 재계산 안 함
    from shapely.ops import unary_union
    static_obstacles = []
    if dead_zones:
        static_obstacles.extend(dz for dz in dead_zones if hasattr(dz, "area"))
    if main_artery:
        static_obstacles.append(main_artery.buffer(600))
    entrance_buffer = space_data.get("entrance_buffer")
    if entrance_buffer:
        static_obstacles.append(entrance_buffer)
    static_cache = unary_union(static_obstacles) if static_obstacles else None

    # slot 목록 추출
    from app.schemas.space_data import extract_slots
    slots = extract_slots(space_data)

    # NetworkX 통로 그래프 초기화 (C7.5 검증용)
    corridor_graph, corridor_nodes, entrance_node = _init_corridor_graph(
        floor_poly, space_data
    )

    # IQI: 면적 밀도 상한 (배치 도중 실시간 체크)
    usable_area = floor_poly.area if floor_poly else 1
    max_footprint = usable_area * 0.25
    cumulative_footprint = sum(
        p.get("width_mm", 0) * p.get("depth_mm", 0)
        for p in placed_polygons
    )

    print(f"[PlacementEngine] start: {len(placements)} placements, "
          f"{len(eligible_objects)} objects, {len(slots)} slots, "
          f"corridor nodes: {len(corridor_nodes) if corridor_nodes else 0}, "
          f"static cache: {'yes' if static_cache else 'no'}, "
          f"density limit: {max_footprint/1_000_000:.1f}m² (25%)")

    for placement in placements:
        obj = obj_map.get(placement.object_type)
        if not obj:
            msg = f"{placement.object_type}: eligible_objects에 없음"
            log.append(msg)
            print(f"[PlacementEngine] SKIP: {msg}")
            failed.append({"object_type": placement.object_type, "reason": msg})
            continue

        # [B] 해당 zone의 slot 필터
        zone_slots = {
            k: v for k, v in slots.items()
            if v.get("zone_label") == placement.zone_label
        }

        # [B2] zone 2차 검증 + 인접 zone 양방향 확장
        if not zone_slots:
            original_zone = placement.zone_label
            expanded_zone = _expand_zone(original_zone, slots)
            if expanded_zone:
                zone_slots = {
                    k: v for k, v in slots.items()
                    if v.get("zone_label") == expanded_zone
                }
                print(f"[PlacementEngine] zone correction: {original_zone} → {expanded_zone} "
                      f"for {placement.object_type}")

        if not zone_slots:
            msg = f"{placement.object_type}: {placement.zone_label}에 slot 없음 (확장 후에도)"
            log.append(msg)
            print(f"[PlacementEngine] SKIP: {msg}")
            failed.append({"object_type": placement.object_type, "reason": msg})
            continue

        # slot 순회 — direction 기반 spine 정렬 분기
        # wall_facing(선반/배너 등 벽면 기물) → far 우선 (반대편 벽면 분산)
        # inward/center(핵심 기물) → adjacent 우선 (주동선 집중)
        spine_order = (_SPINE_FAR_FIRST if placement.direction == "wall_facing"
                       else _SPINE_NEAR_FIRST)
        sorted_slots = sorted(
            zone_slots.items(),
            key=lambda kv: (spine_order.get(kv[1].get("spine_rank", "far"), 9),
                            kv[1].get("walk_mm", 0)),
        )

        placed = False
        for slot_key, slot in sorted_slots:
            # floor_poly를 slot에 주입 (wall_facing 내부 방향 보정용)
            slot["_floor_poly"] = floor_poly

            # 1. 좌표 계산
            result = calculate_position(placement, slot, obj, space_data)
            bbox: Polygon = result["bbox_polygon"]

            # 2. floor polygon 내부 확인 (95% 이상 겹치면 허용 — 벽면 경계 허용)
            if floor_poly:
                overlap = floor_poly.intersection(bbox).area
                ratio = overlap / bbox.area if bbox.area > 0 else 0
                if ratio < 0.95:
                    print(f"[PlacementEngine] {slot_key}: bbox outside floor ({ratio:.0%})")
                    continue

            # 3~4.5. Static Cache 1회 교차 체크 (Dead Zone + Main Artery + Entrance)
            if static_cache and bbox.intersects(static_cache):
                print(f"[PlacementEngine] {slot_key}: static obstacle 침범")
                continue

            # 5. 기배치 오브젝트 충돌 체크
            collision = False
            for existing in placed_polygons:
                intersection = bbox.intersection(existing["bbox_polygon"])
                overlap_area = intersection.area
                if overlap_area <= 0:
                    continue
                # join_pair + overlap_margin_mm: 겹침 깊이가 허용치 이내면 통과
                if _is_join_pair(placement, existing):
                    margin = min(
                        obj.get("overlap_margin_mm", 0),
                        existing.get("overlap_margin_mm", 0),
                    )
                    if margin > 0:
                        # 겹침 깊이: 교집합 bbox의 최소 변 길이
                        ix0, iy0, ix1, iy1 = intersection.bounds
                        overlap_depth = min(ix1 - ix0, iy1 - iy0)
                        if overlap_depth <= margin:
                            continue
                    # margin 없어도 면적 20% 미만이면 허용
                    min_area = min(bbox.area, existing["bbox_polygon"].area)
                    if min_area > 0 and overlap_area / min_area < 0.2:
                        continue
                print(f"[PlacementEngine] {slot_key}: 충돌 with {existing['object_type']}")
                collision = True
                break
            if collision:
                continue

            # 6. 일반 통로 체크 (900mm = buffer 450)
            corridor_blocked = False
            for existing in placed_polygons:
                if _is_join_pair(placement, existing):
                    continue
                gap = bbox.distance(existing["bbox_polygon"])
                if gap < 450 and gap > 0:
                    print(f"[PlacementEngine] {slot_key}: 통로 부족 {gap:.0f}mm < 450mm with {existing['object_type']}")
                    corridor_blocked = True
                    break
            if corridor_blocked:
                continue

            # 7. 관계 제약 검증 (clearspace_mm)
            constraint_violated = _check_pair_constraints(
                placement, bbox, placed_polygons, pair_rules, clearspace_mm
            )
            if constraint_violated:
                print(f"[PlacementEngine] {slot_key}: 관계 제약 위반 — {constraint_violated}")
                continue

            # 7.5. NetworkX 통로 연결성 검증
            if corridor_graph and corridor_nodes and entrance_node:
                if not _check_corridor_connectivity(
                    corridor_graph, corridor_nodes, entrance_node,
                    bbox, slots, placed_polygons,
                ):
                    print(f"[PlacementEngine] {slot_key}: 통로 차단 (NetworkX)")
                    continue

            # 8. Choke Point 동선 병목 검증 (900mm)
            if _check_choke_point_created(
                bbox, placed_polygons, floor_poly, space_data
            ):
                print(f"[PlacementEngine] {slot_key}: 동선 병목 < 900mm (choke point)")
                continue

            # IQI 밀도 체크: 배치 시 점유율 25% 초과 방지
            obj_footprint = obj["width_mm"] * obj["depth_mm"]
            if cumulative_footprint + obj_footprint > max_footprint:
                msg = (f"{placement.object_type}: 밀도 한도 초과 "
                       f"({(cumulative_footprint + obj_footprint)/usable_area*100:.1f}% > 25%)")
                log.append(msg)
                print(f"[PlacementEngine] DENSITY DROP: {msg}")
                failed.append({"object_type": placement.object_type, "reason": msg})
                placed = True  # 루프 탈출 (다음 기물로)
                break

            # 배치 성공
            cumulative_footprint += obj_footprint
            placed_entry = {
                **result,
                "slot_key": slot_key,
                "zone_label": placement.zone_label,
                "direction": placement.direction,
                "placed_because": placement.placed_because,
                "overlap_margin_mm": obj.get("overlap_margin_mm", 0),
                "height_mm": obj.get("height_mm", 1000),
                "category": obj.get("category", ""),
            }
            placed_polygons.append(placed_entry)

            msg = (f"{placement.object_type} → {slot_key} "
                   f"({result['center_x_mm']}, {result['center_y_mm']}) "
                   f"rot={result['rotation_deg']}°")
            log.append(msg)
            print(f"[PlacementEngine] PLACED: {msg}")
            placed = True
            break

        if not placed:
            msg = f"{placement.object_type}: 모든 slot 실패"
            log.append(msg)
            print(f"[PlacementEngine] FAILED: {msg}")
            failed.append({"object_type": placement.object_type, "reason": msg})

    final_pct = (cumulative_footprint / usable_area * 100) if usable_area > 0 else 0
    density_dropped = sum(1 for f in failed if "밀도 한도" in f.get("reason", ""))
    print(f"[PlacementEngine] done: {len(placed_polygons)} placed, {len(failed)} failed, "
          f"총 면적 대비 점유율: {final_pct:.1f}%, 밀도 초과 삭제: {density_dropped}개")

    # existing_placed 제외: 이번 라운드에서 새로 배치된 것만 반환
    new_placed = placed_polygons[len(existing_placed) if existing_placed else 0:]

    return {
        "placed": [_serialize_placed(p) for p in new_placed],
        "_placed_raw": new_placed,  # bbox_polygon 포함 — failure_handler 내부용
        "failed": failed,
        "log": log,
    }


# ── NetworkX 통로 검증 ─────────────────────────────────────────────────────────

# 통로 검증용 buffer (mm)
_CORRIDOR_BUFFER_MM = 450


def _init_corridor_graph(
    floor_poly,
    space_data: dict,
) -> tuple:
    """
    배치 엔진 시작 시 corridor 그래프 초기화.
    Returns: (graph, nodes_dict, entrance_node) or (None, None, None)
    """
    if not floor_poly:
        return None, None, None

    try:
        from app.agents.corridor_graph import build_corridor_graph

        dead_zones = space_data.get("dead_zones", [])
        G, nodes = build_corridor_graph(floor_poly, dead_zones=dead_zones)
        if not nodes:
            return None, None, None

        # entrance 좌표 추출
        entrance_mm = _find_entrance_from_space_data(space_data)
        if not entrance_mm:
            return G, nodes, None

        entrance_node = _nearest_node(nodes, entrance_mm)
        return G, nodes, entrance_node
    except Exception as e:
        print(f"[PlacementEngine] corridor graph init failed: {e}")
        return None, None, None


def _find_entrance_from_space_data(space_data: dict) -> tuple[float, float] | None:
    """space_data에서 entrance mm 좌표 추출."""
    coords = space_data.get("_entrance_coords_mm", [])
    if coords:
        return coords[0]
    return None


def _check_choke_point_created(
    new_bbox: Polygon,
    placed_polygons: list[dict],
    floor_poly: Polygon | None,
    space_data: dict,
) -> bool:
    """
    새 bbox 배치 시 입구→내부 동선이 900mm 미만으로 좁아지는지 검사.
    벽면·기배치 오브젝트와의 gap이 900mm 미만이면서 입구 동선 경로 상에 있으면 True.
    """
    if not floor_poly:
        return False

    MIN_CORRIDOR_MM = 900

    # 새 bbox ↔ 외벽 간 gap 체크
    wall_gap = floor_poly.exterior.distance(new_bbox)
    if 0 < wall_gap < MIN_CORRIDOR_MM:
        # 입구 근처인지 확인 (entrance_buffer 내부이면 동선 차단)
        entrance_buffer = space_data.get("entrance_buffer")
        if entrance_buffer and new_bbox.intersects(entrance_buffer.buffer(MIN_CORRIDOR_MM)):
            return True

    # 새 bbox ↔ 기배치 오브젝트 간 gap 체크
    for existing in placed_polygons:
        ep = existing.get("bbox_polygon")
        if not ep:
            continue
        gap = new_bbox.distance(ep)
        if 0 < gap < MIN_CORRIDOR_MM:
            # 이 gap이 entrance → deep_zone 동선 상에 있는지 체크
            # Main Artery와의 교차 확인
            main_artery = space_data.get("fire", {}).get("main_artery")
            if main_artery:
                # 두 오브젝트의 buffer 교집합이 Main Artery를 가로막는지
                buf_new = new_bbox.buffer(_CORRIDOR_BUFFER_MM)
                buf_old = ep.buffer(_CORRIDOR_BUFFER_MM)
                choke_zone = buf_new.intersection(buf_old)
                if not choke_zone.is_empty and main_artery.intersects(choke_zone):
                    return True

    return False


def _check_corridor_connectivity(
    base_graph: nx.Graph,
    nodes: dict[tuple[int, int], tuple[float, float]],
    entrance_node: tuple[int, int],
    new_bbox: Polygon,
    slots: dict,
    placed_polygons: list[dict],
) -> bool:
    """
    새 bbox를 배치했을 때 entrance → 미배치 slot 경로가 유지되는지 확인.
    incremental: base_graph 복사 후 새 bbox + buffer 영역 내 노드만 제거.
    Returns: True=통로 유지, False=통로 차단
    """
    # 새 bbox + 기배치 bbox를 모두 buffer로 장애물화
    obstacle = new_bbox.buffer(_CORRIDOR_BUFFER_MM)
    for existing in placed_polygons:
        ep = existing.get("bbox_polygon")
        if ep:
            obstacle = obstacle.union(ep.buffer(_CORRIDOR_BUFFER_MM))

    # 그래프 복사 후 장애물 내 노드 제거
    G = base_graph.copy()
    removed = []
    for node_key, (gx, gy) in nodes.items():
        if obstacle.contains(Point(gx, gy)):
            removed.append(node_key)
    G.remove_nodes_from(removed)

    if entrance_node not in G:
        return False

    # 미배치 slot 중 하나라도 도달 가능한지 확인
    placed_slot_keys = {p.get("slot_key") for p in placed_polygons}
    for slot_key, slot_val in slots.items():
        if slot_key in placed_slot_keys:
            continue
        slot_node = _nearest_node(nodes, (slot_val["x_mm"], slot_val["y_mm"]))
        if slot_node in G and nx.has_path(G, entrance_node, slot_node):
            return True  # 최소 1개 slot 도달 가능 → 통로 유지

    return False


# ── 헬퍼 ──────────────────────────────────────────────────────────────────────

# zone 인접 관계: 타겟 기준 양방향 확장 순서
_ZONE_ADJACENCY = {
    "entrance_zone": ["mid_zone"],
    "mid_zone":      ["entrance_zone", "deep_zone"],
    "deep_zone":     ["mid_zone"],
}


def _expand_zone(target_zone: str, slots: dict) -> str | None:
    """
    타겟 zone에 slot이 없을 때 인접 zone으로 확장.
    양방향: deep→mid, mid→entrance/deep, entrance→mid.
    """
    for adj_zone in _ZONE_ADJACENCY.get(target_zone, []):
        has_slot = any(
            v.get("zone_label") == adj_zone
            for v in slots.values()
            if isinstance(v, dict) and "zone_label" in v
        )
        if has_slot:
            return adj_zone
    return None


def _get_clearspace(brand_data: dict) -> float:
    """브랜드 clearspace_mm 추출. 없으면 DEFAULTS 1500."""
    cs = brand_data.get("clearspace_mm", {})
    if isinstance(cs, dict):
        return cs.get("value", 1500)
    return 1500


def _is_join_pair(placement: Placement, existing: dict) -> bool:
    """
    can_join 쌍인지 확인.
    join_with가 명시적으로 설정되어 있고, 상대 object_type과 정확히 일치할 때만 True.
    """
    if not placement.join_with:
        return False
    if not existing.get("object_type"):
        return False
    return placement.join_with == existing["object_type"]


def _check_pair_constraints(
    placement: Placement,
    bbox: Polygon,
    placed: list[dict],
    pair_rules: list,
    clearspace_mm: float,
) -> str | None:
    """
    관계 제약 검증 (Issue 14).
    pair_rules의 각 rule에서 분리 배치 키워드 감지 → distance < clearspace_mm 위반 확인.
    위반 시 사유 문자열 반환, 통과 시 None.
    """
    separation_keywords = ["분리", "떨어", "거리 유지", "다른 존"]

    for rule_entry in pair_rules:
        rule_text = rule_entry.get("rule", "") if isinstance(rule_entry, dict) else str(rule_entry)

        # 현재 오브젝트와 관련된 규칙인지 확인
        obj_type_short = placement.object_type.replace("character_", "")
        if obj_type_short not in rule_text.lower() and placement.object_type not in rule_text.lower():
            continue

        # 분리 규칙인지 확인
        is_separation = any(kw in rule_text for kw in separation_keywords)
        if not is_separation:
            continue

        # 기배치 오브젝트 중 규칙에 언급된 다른 오브젝트 찾기
        for existing in placed:
            existing_short = existing.get("object_type", "").replace("character_", "")
            if existing_short in rule_text.lower() or existing.get("object_type", "") in rule_text.lower():
                dist = bbox.distance(existing["bbox_polygon"])
                if dist < clearspace_mm:
                    return (f"{placement.object_type}↔{existing['object_type']}: "
                            f"{dist:.0f}mm < {clearspace_mm}mm ({rule_text})")

    return None


def _serialize_placed(p: dict) -> dict:
    """Shapely 객체 제거 후 직렬화 가능한 dict 반환."""
    bbox: Polygon = p["bbox_polygon"]

    # category 유실 차단
    if "category" not in p or p["category"] is None:
        print(f"[CRITICAL] Serialization: category missing for {p.get('object_type', '?')} — defaulting to ''")

    return {
        "object_type": p["object_type"],
        "center_x_mm": p["center_x_mm"],
        "center_y_mm": p["center_y_mm"],
        "rotation_deg": p["rotation_deg"],
        "width_mm": p["width_mm"],
        "depth_mm": p["depth_mm"],
        "height_mm": p.get("height_mm", 1000),
        "category": p.get("category", ""),
        "slot_key": p["slot_key"],
        "zone_label": p["zone_label"],
        "direction": p["direction"],
        "placed_because": p["placed_because"],
        "bbox_bounds": [round(b) for b in bbox.bounds],
    }
