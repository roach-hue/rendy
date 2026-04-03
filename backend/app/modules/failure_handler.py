"""
P0-5c — 실패 처리 모듈

cascade failure 감지 + Deterministic Fallback 3단계.
Agent 3 재호출은 LLM 구현(Agent 3) 이후 연결 — 현재는 피드백 생성까지만.

3단계 fallback (Issue 15):
  1단계: 정상 흐름 (placement_engine.run_placement_loop)
  2단계: Global Reset 최대 2회 — Choke Point 피드백 생성 → Agent 3 재호출
  3단계: deterministic fallback — zone 무시, priority 순, 벽 최인접 강제 배치
"""
from shapely.geometry import LineString, Point, Polygon

from app.schemas.placement import Placement
from app.modules.placement_engine import run_placement_loop


MAX_GLOBAL_RESETS = 2


def run_with_fallback(
    placements: list[Placement],
    eligible_objects: list[dict],
    space_data: dict,
    brand_data: dict,
) -> dict:
    """
    배치 엔진 + 실패 처리 통합 진입점.

    Returns:
        {
            "placed": [...],
            "failed": [...],
            "dropped": [...],  # Graceful Degradation으로 드랍된 오브젝트
            "log": [...],
            "fallback_used": bool,
            "reset_count": int,
        }
    """
    # 1단계: 정상 흐름
    result = run_placement_loop(placements, eligible_objects, space_data, brand_data)
    # placed_with_poly: bbox_polygon이 포함된 원본 리스트 (충돌 체크용)
    placed_with_poly: list[dict] = list(result.get("_placed_raw", result["placed"]))

    if not result["failed"]:
        print(f"[FailureHandler] all placed on first try")
        return {**result, "dropped": [], "fallback_used": False, "reset_count": 0}

    # Global Reset 폐기 — Agent 3 재호출 없이 동일 조건 재시도는 무의미
    cascade_objects, physical_limit_objects = _classify_failures(
        result["failed"], eligible_objects, space_data, brand_data,
        original_placements=placements,
    )
    print(f"[FailureHandler] {len(cascade_objects)} cascade, "
          f"{len(physical_limit_objects)} physical limit → deterministic fallback")

    # Deterministic Fallback (즉시 진입)
    dropped = []
    if result["failed"]:
        print(f"[FailureHandler] entering deterministic fallback for {len(result['failed'])} objects")
        fallback_result = _deterministic_fallback(
            result["failed"], eligible_objects, space_data, placed_with_poly
        )
        result["placed"].extend(fallback_result["placed"])
        dropped = fallback_result["dropped"]
        result["log"].extend(fallback_result["log"])

    print(f"[FailureHandler] final: {len(result['placed'])} placed, {len(dropped)} dropped")

    return {
        "placed": result["placed"],
        "failed": [],
        "dropped": dropped,
        "log": result["log"],
        "fallback_used": len(dropped) > 0 or len(result["failed"]) > 0,
        "reset_count": 0,
    }


# ── cascade 분류 ──────────────────────────────────────────────────────────────

def _classify_failures(
    failed: list[dict],
    eligible_objects: list[dict],
    space_data: dict,
    brand_data: dict,
    original_placements: list[Placement] | None = None,
) -> tuple[list[dict], list[dict]]:
    """
    실패 오브젝트를 cascade vs 물리적 한계로 분류.
    단독 배치 테스트: 빈 공간에서 해당 오브젝트만 배치 시도.
    원본 placement의 zone_label/direction을 유지하여 테스트.
    """
    cascade = []
    physical = []

    # 원본 placement에서 zone_label/direction 조회용 맵
    orig_map = {}
    if original_placements:
        for p in original_placements:
            orig_map[p.object_type] = p

    # 사용 가능한 zone 목록 추출
    available_zones = set()
    for k, v in space_data.items():
        if isinstance(v, dict) and "zone_label" in v and k != "floor":
            available_zones.add(v["zone_label"])

    for f in failed:
        obj_type = f["object_type"]
        orig = orig_map.get(obj_type)

        # 원본이 있으면 원본 zone/direction 사용, 없으면 전체 zone 순회
        test_zones = [orig.zone_label] if orig else list(available_zones)
        test_dir = orig.direction if orig else "wall_facing"

        placed = False
        for zone in test_zones:
            test_placement = Placement(
                object_type=obj_type,
                zone_label=zone,
                direction=test_dir,
                priority=1,
                placed_because="단독 배치 테스트",
            )
            test_result = run_placement_loop(
                [test_placement], eligible_objects, space_data, brand_data
            )
            if test_result["placed"]:
                placed = True
                break

        if placed:
            cascade.append(f)
            print(f"[FailureHandler] {obj_type}: cascade (단독 배치 성공)")
        else:
            physical.append(f)
            print(f"[FailureHandler] {obj_type}: physical limit (단독 배치도 실패)")

    return cascade, physical


# ── Choke Point 피드백 ───────────────────────────────────────────────────────

def _generate_choke_feedback(
    cascade_objects: list[dict],
    placed: list[dict],
    space_data: dict,
) -> str:
    """
    Issue 12 — Choke Point intersects로 원인 추출 + f-string 피드백.
    placed_objects JSON 전달 금지.
    """
    lines = []
    for obj in cascade_objects:
        obj_type = obj["object_type"]
        reason = obj.get("reason", "unknown")
        lines.append(f"- {obj_type} 배치 실패: {reason}")

    lines.append(f"\n현재 배치 완료: {len(placed)}개")
    lines.append("남은 slot에 재배치를 시도하세요.")

    return "\n".join(lines)


# ── Deterministic Fallback ───────────────────────────────────────────────────

def _deterministic_fallback(
    failed: list[dict],
    eligible_objects: list[dict],
    space_data: dict,
    already_placed: list[dict],
) -> dict:
    """
    Issue 15 — 3단계 deterministic fallback.
    LLM 개입 없이 코드가 강제 배치:
    ① priority 높은 순
    ② zone 제약 무시 — 전체 slot 탐색
    ③ entrance blocking 금지
    ④ 벽 최인접 선택
    ⑤ 불가 → Graceful Degradation (드랍)
    """
    obj_map = {o["object_type"]: o for o in eligible_objects}
    all_slots = {
        k: v for k, v in space_data.items()
        if isinstance(v, dict) and "zone_label" in v and k != "floor"
    }

    placed = []  # bbox_polygon 포함 raw dict
    dropped = []
    log = []

    sorted_slots = sorted(all_slots.items(), key=lambda kv: kv[1].get("walk_mm", 0))
    # already_placed는 bbox_polygon 포함 raw 리스트
    all_existing = list(already_placed)

    for f in failed:
        obj_type = f["object_type"]
        obj = obj_map.get(obj_type)
        if not obj:
            dropped.append({"object_type": obj_type, "reason": "eligible 목록에 없음"})
            continue

        fallback_placement = Placement(
            object_type=obj_type,
            zone_label="entrance_zone",
            direction="wall_facing",
            priority=99,
            placed_because="deterministic fallback 강제 배치",
        )

        success = False
        for slot_key, slot in sorted_slots:
            from app.modules.calculate_position import calculate_position
            result = calculate_position(fallback_placement, slot, obj, space_data)
            bbox = result["bbox_polygon"]

            entrance = _find_entrance(space_data)
            if entrance and Point(entrance).distance(bbox) < 2000:
                continue

            # Main Artery 체크
            main_artery = space_data.get("fire", {}).get("main_artery")
            if main_artery and bbox.intersects(main_artery.buffer(600)):
                continue

            # Dead Zone 체크
            dead_zones = space_data.get("dead_zones", [])
            if any(bbox.intersects(dz) for dz in dead_zones):
                continue

            # Virtual Entrance 체크
            entrance_buffer = space_data.get("entrance_buffer")
            if entrance_buffer and bbox.intersects(entrance_buffer):
                continue

            # 충돌 확인: all_existing = 이전 배치 + fallback 내 신규 배치
            collision = False
            for existing in all_existing:
                existing_poly = existing.get("bbox_polygon")
                if existing_poly and bbox.intersection(existing_poly).area > 0:
                    collision = True
                    break
            if collision:
                continue

            floor_poly = space_data.get("floor", {}).get("polygon")
            if floor_poly:
                overlap = floor_poly.intersection(bbox).area
                if overlap / bbox.area < 0.95:
                    continue

            placed_entry = {
                **result,
                "slot_key": slot_key,
                "zone_label": slot.get("zone_label", "unknown"),
                "direction": "wall_facing",
                "placed_because": "deterministic fallback 강제 배치",
                "source": "fallback",
            }
            placed.append(placed_entry)
            all_existing.append(placed_entry)  # 즉시 추가 → 다음 기물이 인식
            msg = f"FALLBACK: {obj_type} → {slot_key}"
            log.append(msg)
            print(f"[FailureHandler] {msg}")
            success = True
            break

        if not success:
            dropped.append({"object_type": obj_type, "reason": "모든 slot 실패 (Graceful Degradation)"})
            log.append(f"DROPPED: {obj_type}")
            print(f"[FailureHandler] DROPPED: {obj_type}")

    return {"placed": [_serialize_fallback(p) for p in placed], "dropped": dropped, "log": log}


def _serialize_fallback(p: dict) -> dict:
    """fallback 배치 결과 직렬화 (bbox_polygon 제거)."""
    from shapely.geometry import Polygon as _Poly
    bbox = p.get("bbox_polygon")
    return {
        "object_type": p["object_type"],
        "center_x_mm": p["center_x_mm"],
        "center_y_mm": p["center_y_mm"],
        "rotation_deg": p["rotation_deg"],
        "width_mm": p["width_mm"],
        "depth_mm": p["depth_mm"],
        "slot_key": p["slot_key"],
        "zone_label": p["zone_label"],
        "direction": p["direction"],
        "placed_because": p["placed_because"],
        "bbox_bounds": [round(b) for b in bbox.bounds] if isinstance(bbox, _Poly) else [],
    }


def _find_entrance(space_data: dict) -> tuple[float, float] | None:
    """space_data에서 walk_mm 최소 slot = entrance 근사."""
    min_walk = float("inf")
    entrance = None
    for k, v in space_data.items():
        if isinstance(v, dict) and "walk_mm" in v:
            if v["walk_mm"] < min_walk:
                min_walk = v["walk_mm"]
                entrance = (v.get("x_mm", 0), v.get("y_mm", 0))
    return entrance
