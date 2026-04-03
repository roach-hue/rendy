"""
P0-6 — 소방/시공 최종 검증 모듈

배치 완료 후 전체 결과에 대해 최종 검증 실행.
blocking(배치 무효) vs warning(경고만) 분류.

검증 항목:
  1. 소방 주통로 900mm 이상
  2. 비상 대피로 1200mm 이상 (Main Artery)
  3. Dead Zone 침범
  4. 벽체 이격 300mm
  5. floor polygon 이탈
"""
from shapely.geometry import LineString, Polygon

from app.modules.calculate_position import _make_rotated_rect
from app.schemas.verification import VerificationResult, ViolationItem


def verify_placement(
    placed: list[dict],
    space_data: dict,
) -> VerificationResult:
    """
    최종 검증 실행. Pydantic VerificationResult 반환.
    """
    blocking: list[ViolationItem] = []
    warning: list[ViolationItem] = []

    floor_poly: Polygon = space_data.get("floor", {}).get("polygon")
    dead_zones: list = space_data.get("dead_zones", [])
    main_artery: LineString | None = space_data.get("fire", {}).get("main_artery")

    # bbox polygon 재구성 (직렬화된 결과에서 복원)
    polys = []
    for p in placed:
        if "bbox_polygon" in p and hasattr(p["bbox_polygon"], "area"):
            polys.append(p)
        else:
            bbox = _make_rotated_rect(
                (p["center_x_mm"], p["center_y_mm"]),
                p["width_mm"], p["depth_mm"],
                p["rotation_deg"],
            )
            polys.append({**p, "bbox_polygon": bbox})

    print(f"[Verification] checking {len(polys)} objects")

    for i, obj in enumerate(polys):
        bbox = obj["bbox_polygon"]
        obj_type = obj["object_type"]

        # 1. floor polygon 이탈
        if floor_poly:
            overlap = floor_poly.intersection(bbox).area
            ratio = overlap / bbox.area if bbox.area > 0 else 0
            if ratio < 0.95:
                blocking.append(ViolationItem(
                    object_type=obj_type,
                    rule="floor_exit",
                    severity="blocking",
                    detail=f"floor polygon 이탈 ({ratio:.0%} 내부)",
                ))
                print(f"[Verification] BLOCK: {obj_type} floor 이탈 ({ratio:.0%})")

        # 2. Dead Zone 침범
        for dz in dead_zones:
            if bbox.intersects(dz):
                blocking.append(ViolationItem(
                    object_type=obj_type,
                    rule="dead_zone",
                    severity="blocking",
                    detail="Dead Zone 침범",
                ))
                print(f"[Verification] BLOCK: {obj_type} Dead Zone 침범")
                break

        # 3. Main Artery 1200mm
        if main_artery:
            artery_buffer = main_artery.buffer(600)
            if bbox.intersects(artery_buffer):
                blocking.append(ViolationItem(
                    object_type=obj_type,
                    rule="main_artery",
                    severity="blocking",
                    detail="비상 대피로 1200mm 침범",
                ))
                print(f"[Verification] BLOCK: {obj_type} Main Artery 침범")

        # 4. 오브젝트 간 통로 900mm
        for j, other in enumerate(polys):
            if i >= j:
                continue
            other_bbox = other["bbox_polygon"]
            gap = bbox.distance(other_bbox)
            if 0 < gap < 900:
                warning.append(ViolationItem(
                    object_type=f"{obj_type}↔{other['object_type']}",
                    rule="corridor",
                    severity="warning",
                    detail=f"통로 {gap:.0f}mm < 900mm",
                ))
                print(f"[Verification] WARN: {obj_type}↔{other['object_type']} gap={gap:.0f}mm")

        # 5. 벽체 이격 300mm
        if floor_poly:
            wall_dist = floor_poly.exterior.distance(bbox)
            if obj.get("direction") != "wall_facing" and wall_dist < 300:
                warning.append(ViolationItem(
                    object_type=obj_type,
                    rule="wall_clearance",
                    severity="warning",
                    detail=f"벽체 이격 {wall_dist:.0f}mm < 300mm",
                ))
                print(f"[Verification] WARN: {obj_type} wall dist={wall_dist:.0f}mm")

    is_pass = len(blocking) == 0
    print(f"[Verification] result: {'PASS' if is_pass else 'FAIL'} — "
          f"{len(blocking)} blocking, {len(warning)} warnings")

    return VerificationResult(
        passed=is_pass,
        blocking=blocking,
        warning=warning,
        checked_count=len(polys),
    )
