"""
P0-6 테스트 — verification

실행: cd backend && PYTHONIOENCODING=utf-8 python -m tests.test_p06
"""
from shapely.geometry import LineString, Point, Polygon

from app.modules.verification import verify_placement


def _make_space_data():
    floor_poly = Polygon([(0, 0), (12000, 0), (12000, 8000), (0, 8000)])
    return {
        "floor": {"polygon": floor_poly},
        "fire": {"main_artery": LineString([(6000, 8000), (6000, 0)])},
        "dead_zones": [Point(3000, 2000).buffer(300)],
    }


def test_clean_pass():
    print("\n" + "=" * 60)
    print("TEST: clean pass")
    print("=" * 60)

    sd = _make_space_data()
    placed = [
        {"object_type": "shelf", "center_x_mm": 2000, "center_y_mm": 7600,
         "width_mm": 1200, "depth_mm": 400, "rotation_deg": 0, "direction": "wall_facing"},
        {"object_type": "character", "center_x_mm": 9000, "center_y_mm": 4000,
         "width_mm": 800, "depth_mm": 800, "rotation_deg": 0, "direction": "inward"},
    ]

    result = verify_placement(placed, sd)
    assert result["pass"] is True
    assert len(result["blocking"]) == 0
    print(f"  blocking: {len(result['blocking'])}, warnings: {len(result['warning'])}")
    print("PASS")


def test_dead_zone_violation():
    print("\n" + "=" * 60)
    print("TEST: dead zone violation")
    print("=" * 60)

    sd = _make_space_data()
    placed = [
        {"object_type": "shelf_on_sprinkler", "center_x_mm": 3000, "center_y_mm": 2000,
         "width_mm": 800, "depth_mm": 400, "rotation_deg": 0, "direction": "inward"},
    ]

    result = verify_placement(placed, sd)
    assert result["pass"] is False
    assert any("Dead Zone" in b["violation"] for b in result["blocking"])
    print(f"  blocking: {result['blocking']}")
    print("PASS")


def test_main_artery_violation():
    print("\n" + "=" * 60)
    print("TEST: main artery violation")
    print("=" * 60)

    sd = _make_space_data()
    placed = [
        {"object_type": "table_on_artery", "center_x_mm": 6000, "center_y_mm": 4000,
         "width_mm": 1200, "depth_mm": 600, "rotation_deg": 0, "direction": "center"},
    ]

    result = verify_placement(placed, sd)
    assert result["pass"] is False
    assert any("1200mm" in b["violation"] for b in result["blocking"])
    print(f"  blocking: {result['blocking']}")
    print("PASS")


def test_narrow_gap_warning():
    print("\n" + "=" * 60)
    print("TEST: narrow gap warning (< 900mm)")
    print("=" * 60)

    sd = _make_space_data()
    placed = [
        {"object_type": "shelf_a", "center_x_mm": 2000, "center_y_mm": 4000,
         "width_mm": 1200, "depth_mm": 400, "rotation_deg": 0, "direction": "wall_facing"},
        {"object_type": "shelf_b", "center_x_mm": 2000, "center_y_mm": 4600,
         "width_mm": 1200, "depth_mm": 400, "rotation_deg": 0, "direction": "wall_facing"},
    ]

    result = verify_placement(placed, sd)
    assert len(result["warning"]) > 0
    print(f"  warnings: {result['warning']}")
    print("PASS")


if __name__ == "__main__":
    test_clean_pass()
    test_dead_zone_violation()
    test_main_artery_violation()
    test_narrow_gap_warning()
    print("\n" + "=" * 60)
    print("ALL P0-6 TESTS PASSED")
    print("=" * 60)
