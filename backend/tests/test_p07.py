"""
P0-7 통합 테스트 — report + glb export

실행: cd backend && PYTHONIOENCODING=utf-8 python -m tests.test_p07
"""
from shapely.geometry import LineString, Point, Polygon

from app.modules.report_generator import generate_report
from app.modules.glb_exporter import export_glb
from app.modules.verification import verify_placement


def _make_test_data():
    floor_poly = Polygon([(0, 0), (12000, 0), (12000, 8000), (0, 8000)])

    space_data = {
        "floor": {
            "polygon": floor_poly,
            "usable_area_sqm": 96.0,
            "max_object_w_mm": 2600,
            "ceiling_height_mm": {"value": 3000, "confidence": "high", "source": "default"},
        },
        "fire": {
            "main_artery": LineString([(6000, 8000), (6000, 0)]),
        },
        "dead_zones": [],
    }

    brand_data = {
        "clearspace_mm": {"value": 1500, "confidence": "high", "source": "manual"},
        "logo_clearspace_mm": {"value": 500, "confidence": "high", "source": "manual"},
        "character_orientation": {"value": "entrance facing", "confidence": "high", "source": "manual"},
        "prohibited_material": {"value": "metal", "confidence": "high", "source": "manual"},
        "object_pair_rules": [
            {"rule": "kuromi-hellokitty 3000mm separation", "confidence": "high"},
        ],
    }

    placed = [
        {
            "object_type": "shelf_3tier", "center_x_mm": 3000, "center_y_mm": 7800,
            "width_mm": 1200, "depth_mm": 400, "height_mm": 1200, "rotation_deg": 0,
            "slot_key": "south_wall_slot_0_1", "zone_label": "entrance_zone",
            "direction": "wall_facing",
            "placed_because": "entrance first impression",
        },
        {
            "object_type": "character_hellokitty", "center_x_mm": 500, "center_y_mm": 4000,
            "width_mm": 800, "depth_mm": 800, "height_mm": 2000, "rotation_deg": 58,
            "slot_key": "west_wall_slot_0_1", "zone_label": "mid_zone",
            "direction": "inward",
            "placed_because": "mid zone photo point",
        },
        {
            "object_type": "photo_zone_structure", "center_x_mm": 3000, "center_y_mm": 750,
            "width_mm": 2000, "depth_mm": 1500, "height_mm": 2400, "rotation_deg": 180,
            "slot_key": "north_wall_slot_0_1", "zone_label": "deep_zone",
            "direction": "wall_facing",
            "placed_because": "deep zone main attraction",
        },
    ]

    dropped = []

    return space_data, brand_data, placed, dropped


def test_report():
    print("\n" + "=" * 60)
    print("TEST: report generation")
    print("=" * 60)

    sd, bd, placed, dropped = _make_test_data()
    verification = verify_placement(placed, sd)

    report = generate_report(placed, dropped, verification, sd, bd, fallback_used=False)
    print(report[:500])
    print(f"  ...({len(report)} chars total)")

    assert "shelf_3tier" in report
    assert "character_hellokitty" in report
    assert "PASS" in report or "FAIL" in report
    print("PASS")


def test_glb_export():
    print("\n" + "=" * 60)
    print("TEST: .glb export")
    print("=" * 60)

    sd, bd, placed, dropped = _make_test_data()

    glb_bytes = export_glb(placed, sd, output_path="test_results/test_output.glb")
    assert len(glb_bytes) > 100, f"GLB too small: {len(glb_bytes)} bytes"
    print(f"  .glb size: {len(glb_bytes)} bytes")

    # 파일 존재 확인
    from pathlib import Path
    assert Path("test_results/test_output.glb").exists()
    print("PASS")


if __name__ == "__main__":
    test_report()
    test_glb_export()
    print("\n" + "=" * 60)
    print("ALL P0-7 TESTS PASSED")
    print("=" * 60)
