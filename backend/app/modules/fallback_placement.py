"""Deterministic Fallback — zone 무시, 전체 slot 강제 배치."""
from shapely.geometry import Point

from app.schemas.placement import Placement
from app.api.serializer import strip_shapely


def deterministic_fallback(
    failed: list[dict],
    eligible_objects: list[dict],
    space_data: dict,
    already_placed: list[dict],
) -> dict:
    """zone 무시, 전체 slot 강제 배치. 불가 시 drop."""
    obj_map = {o["object_type"]: o for o in eligible_objects}
    all_slots = {
        k: v for k, v in space_data.items()
        if isinstance(v, dict) and "zone_label" in v and k != "floor"
    }

    placed = []
    dropped = []
    log = []

    sorted_slots = sorted(all_slots.items(), key=lambda kv: kv[1].get("walk_mm", 0))
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
            placed_because="deterministic fallback",
        )

        success = False
        for slot_key, slot in sorted_slots:
            from app.modules.calculate_position import calculate_position
            result = calculate_position(fallback_placement, slot, obj, space_data)
            bbox = result["bbox_polygon"]

            entrance = _find_entrance(space_data)
            if entrance and Point(entrance).distance(bbox) < 2000:
                continue

            main_artery = space_data.get("fire", {}).get("main_artery")
            if main_artery and bbox.intersects(main_artery.buffer(600)):
                continue

            dead_zones = space_data.get("dead_zones", [])
            if any(bbox.intersects(dz) for dz in dead_zones):
                continue

            entrance_buffer = space_data.get("entrance_buffer")
            if entrance_buffer and bbox.intersects(entrance_buffer):
                continue

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
                "placed_because": "deterministic fallback",
                "source": "fallback",
                "height_mm": obj.get("height_mm", 1000),
                "category": obj.get("category", ""),
            }
            placed.append(placed_entry)
            all_existing.append(placed_entry)
            log.append(f"FALLBACK: {obj_type} → {slot_key}")
            print(f"[FallbackPlacement] FALLBACK: {obj_type} → {slot_key}")
            success = True
            break

        if not success:
            dropped.append({"object_type": obj_type, "reason": "Graceful Degradation"})
            log.append(f"DROPPED: {obj_type}")
            print(f"[FallbackPlacement] DROPPED: {obj_type}")

    return {
        "placed": [_serialize_placed(p) for p in placed],
        "dropped": dropped,
        "log": log,
    }


def _serialize_placed(p: dict) -> dict:
    """fallback 배치 결과 직렬화 — placement_engine과 동일 스키마 강제."""
    from shapely.geometry import Polygon as _Poly
    bbox = p.get("bbox_polygon")

    # category 유실 차단
    if "category" not in p or p["category"] is None:
        print(f"[CRITICAL] Serialization: category missing for {p.get('object_type', '?')} — defaulting to ''")
        p["category"] = ""

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
        "bbox_bounds": [round(b) for b in bbox.bounds] if isinstance(bbox, _Poly) else [],
    }


def _find_entrance(space_data: dict) -> tuple[float, float] | None:
    min_walk = float("inf")
    entrance = None
    for k, v in space_data.items():
        if isinstance(v, dict) and "walk_mm" in v:
            if v["walk_mm"] < min_walk:
                min_walk = v["walk_mm"]
                entrance = (v.get("x_mm", 0), v.get("y_mm", 0))
    return entrance
