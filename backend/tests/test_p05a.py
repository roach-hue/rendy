"""
P0-5a 단위 테스트 — calculate_position + object_selection

실행: cd backend && python test_p05a.py
"""
import json
from shapely.geometry import LineString, Polygon

from app.schemas.placement import Placement
from app.modules.calculate_position import calculate_position
from app.modules.object_selection import select_eligible_objects


def _make_mock_space_data() -> dict:
    """테스트용 space_data (12000x8000mm 직사각형 공간)."""
    floor_poly = Polygon([
        (0, 0), (12000, 0), (12000, 8000), (0, 8000)
    ])

    sd: dict = {
        "floor": {
            "polygon": floor_poly,
            "usable_area_sqm": 96.0,
            "max_object_w_mm": 2600,
            "ceiling_height_mm": {"value": 3000, "confidence": "high", "source": "default"},
        },
        "fire": {
            "main_corridor_min_mm": 900,
            "emergency_path_min_mm": 1200,
        },
        "dead_zones": [],
        "infra": {"disclaimer": []},
    }

    # 벽면 슬롯 4개 (각 벽 1개씩)
    sd["south_wall_slot_0_1"] = {
        "x_mm": 6000, "y_mm": 8000,
        "wall_linestring": LineString([(0, 8000), (12000, 8000)]),
        "wall_normal": "north",
        "zone_label": "entrance_zone",
        "walk_mm": 1000, "shelf_capacity": 6,
    }
    sd["north_wall_slot_0_1"] = {
        "x_mm": 6000, "y_mm": 0,
        "wall_linestring": LineString([(0, 0), (12000, 0)]),
        "wall_normal": "south",
        "zone_label": "deep_zone",
        "walk_mm": 8000, "shelf_capacity": 6,
    }
    sd["east_wall_slot_0_1"] = {
        "x_mm": 12000, "y_mm": 4000,
        "wall_linestring": LineString([(12000, 0), (12000, 8000)]),
        "wall_normal": "west",
        "zone_label": "mid_zone",
        "walk_mm": 5000, "shelf_capacity": 4,
    }
    sd["west_wall_slot_0_1"] = {
        "x_mm": 0, "y_mm": 4000,
        "wall_linestring": LineString([(0, 0), (0, 8000)]),
        "wall_normal": "east",
        "zone_label": "mid_zone",
        "walk_mm": 5000, "shelf_capacity": 4,
    }

    return sd


def test_wall_facing():
    """wall_facing: 남벽 중앙에 선반 배치."""
    print("\n" + "=" * 60)
    print("TEST: wall_facing — 남벽 중앙 선반")
    print("=" * 60)

    sd = _make_mock_space_data()
    slot = sd["south_wall_slot_0_1"]
    obj = {"object_type": "shelf_3tier", "width_mm": 1200, "depth_mm": 400, "height_mm": 1200}

    placement = Placement(
        object_type="shelf_3tier",
        zone_label="entrance_zone",
        direction="wall_facing",
        priority=1,
        placed_because="입구 진입 시 첫 시선이 닿는 곳에 제품 진열",
    )

    result = calculate_position(placement, slot, obj, sd)
    _print_result(result)

    # 검증: 중심이 벽에서 depth/2 = 200mm 안쪽
    assert abs(result["center_y_mm"] - 7800) < 1, f"center_y should be 7800, got {result['center_y_mm']}"
    assert abs(result["center_x_mm"] - 6000) < 1, f"center_x should be 6000, got {result['center_x_mm']}"
    print("✓ PASS")


def test_inward():
    """inward: 동벽 슬롯에서 entrance 방향 바라보기."""
    print("\n" + "=" * 60)
    print("TEST: inward — 동벽 슬롯, entrance 바라봄")
    print("=" * 60)

    sd = _make_mock_space_data()
    slot = sd["east_wall_slot_0_1"]
    obj = {"object_type": "character_hellokitty", "width_mm": 800, "depth_mm": 800, "height_mm": 2000}

    placement = Placement(
        object_type="character_hellokitty",
        zone_label="mid_zone",
        direction="inward",
        priority=2,
        placed_because="메인 동선 중간에 포토 포인트 역할",
    )

    result = calculate_position(placement, slot, obj, sd)
    _print_result(result)

    # inward는 격자점 = 중심, 오프셋 없음
    assert abs(result["center_x_mm"] - 12000) < 1
    assert abs(result["center_y_mm"] - 4000) < 1
    print("✓ PASS")


def test_center():
    """center: 서벽 슬롯에서 floor center 바라봄."""
    print("\n" + "=" * 60)
    print("TEST: center — 서벽 슬롯, floor center 바라봄")
    print("=" * 60)

    sd = _make_mock_space_data()
    slot = sd["west_wall_slot_0_1"]
    obj = {"object_type": "display_table", "width_mm": 1200, "depth_mm": 600, "height_mm": 800}

    placement = Placement(
        object_type="display_table",
        zone_label="mid_zone",
        direction="center",
        priority=3,
        placed_because="공간 중앙 방향으로 전시 테이블 배치",
    )

    result = calculate_position(placement, slot, obj, sd)
    _print_result(result)
    print("✓ PASS")


def test_rotation_override():
    """rotation_deg 15° 안전장치 테스트."""
    print("\n" + "=" * 60)
    print("TEST: rotation_deg 안전장치")
    print("=" * 60)

    sd = _make_mock_space_data()
    slot = sd["south_wall_slot_0_1"]
    obj = {"object_type": "shelf_3tier", "width_mm": 1200, "depth_mm": 400, "height_mm": 1200}

    # Case 1: 5° 차이 → 무시
    p1 = Placement(
        object_type="shelf_3tier",
        zone_label="entrance_zone",
        direction="wall_facing",
        priority=1,
        rotation_deg=275.0,  # code angle ≈ 270° (north normal), 차이 5°
        placed_because="선반 미세 조정",
    )
    r1 = calculate_position(p1, slot, obj, sd)
    print(f"  Case 1 (5° diff): final={r1['rotation_deg']}° — should use code angle")

    # Case 2: 45° 차이 → 채택
    p2 = Placement(
        object_type="shelf_3tier",
        zone_label="entrance_zone",
        direction="wall_facing",
        priority=1,
        rotation_deg=225.0,  # code angle ≈ 270°, 차이 45°
        placed_because="선반 대각 배치 의도",
    )
    r2 = calculate_position(p2, slot, obj, sd)
    print(f"  Case 2 (45° diff): final={r2['rotation_deg']}° — should be 225.0°")
    assert abs(r2["rotation_deg"] - 225.0) < 1, f"Expected 225.0, got {r2['rotation_deg']}"

    print("✓ PASS")


def test_object_selection():
    """오브젝트 선별 모듈 테스트."""
    print("\n" + "=" * 60)
    print("TEST: object_selection")
    print("=" * 60)

    sd = _make_mock_space_data()
    brand = {
        "clearspace_mm": {"value": 1500, "confidence": "high", "source": "manual"},
        "prohibited_material": {"value": "metal", "confidence": "high", "source": "manual"},
    }

    eligible = select_eligible_objects(sd, brand)
    types = [o["object_type"] for o in eligible]
    print(f"  eligible: {types}")

    # banner_stand는 material=fabric_metal_frame → "metal" 포함 → 필터됨
    assert "banner_stand" not in types, "banner_stand should be filtered (metal)"
    print("✓ PASS")


def _print_result(r: dict):
    """결과 출력 (Shapely 객체 제외)."""
    display = {k: v for k, v in r.items() if k != "bbox_polygon"}
    display["bbox_area_mm2"] = round(r["bbox_polygon"].area)
    display["bbox_bounds"] = [round(b) for b in r["bbox_polygon"].bounds]
    print(f"  result: {json.dumps(display, ensure_ascii=False)}")


if __name__ == "__main__":
    test_wall_facing()
    test_inward()
    test_center()
    test_rotation_override()
    test_object_selection()
    print("\n" + "=" * 60)
    print("ALL TESTS PASSED")
    print("=" * 60)
