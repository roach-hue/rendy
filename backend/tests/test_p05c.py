"""
P0-5c 테스트 — failure_handler (cascade + deterministic fallback)

실행: cd backend && PYTHONIOENCODING=utf-8 python -m tests.test_p05c
"""
from shapely.geometry import LineString, Point, Polygon

from app.schemas.placement import Placement
from app.modules.failure_handler import run_with_fallback
from app.modules.object_selection import MOCK_OBJECTS


def _make_space_data():
    floor_poly = Polygon([(0, 0), (12000, 0), (12000, 8000), (0, 8000)])
    sd = {
        "floor": {
            "polygon": floor_poly,
            "usable_area_sqm": 96.0,
            "max_object_w_mm": 2600,
            "ceiling_height_mm": {"value": 3000, "confidence": "high", "source": "default"},
        },
        "fire": {
            "main_corridor_min_mm": 900,
            "emergency_path_min_mm": 1200,
            "main_artery": LineString([(6000, 8000), (6000, 0)]),
        },
        "dead_zones": [],
        "infra": {"disclaimer": []},
    }
    sd["south_wall_slot_0_1"] = {
        "x_mm": 3000, "y_mm": 8000,
        "wall_linestring": LineString([(0, 8000), (12000, 8000)]),
        "wall_normal": "north", "zone_label": "entrance_zone",
        "walk_mm": 500, "shelf_capacity": 6,
    }
    sd["south_wall_slot_0_2"] = {
        "x_mm": 9000, "y_mm": 8000,
        "wall_linestring": LineString([(0, 8000), (12000, 8000)]),
        "wall_normal": "north", "zone_label": "entrance_zone",
        "walk_mm": 1500, "shelf_capacity": 6,
    }
    sd["north_wall_slot_0_1"] = {
        "x_mm": 3000, "y_mm": 0,
        "wall_linestring": LineString([(0, 0), (12000, 0)]),
        "wall_normal": "south", "zone_label": "deep_zone",
        "walk_mm": 9000, "shelf_capacity": 6,
    }
    sd["north_wall_slot_0_2"] = {
        "x_mm": 9000, "y_mm": 0,
        "wall_linestring": LineString([(0, 0), (12000, 0)]),
        "wall_normal": "south", "zone_label": "deep_zone",
        "walk_mm": 9500, "shelf_capacity": 6,
    }
    sd["west_wall_slot_0_1"] = {
        "x_mm": 0, "y_mm": 4000,
        "wall_linestring": LineString([(0, 0), (0, 8000)]),
        "wall_normal": "east", "zone_label": "mid_zone",
        "walk_mm": 5000, "shelf_capacity": 4,
    }
    return sd


def test_all_success():
    """fallback 불필요 케이스."""
    print("\n" + "=" * 60)
    print("TEST: all success (no fallback)")
    print("=" * 60)

    sd = _make_space_data()
    brand = {"clearspace_mm": {"value": 1500}, "object_pair_rules": []}

    placements = [
        Placement(object_type="shelf_3tier", zone_label="entrance_zone",
                  direction="wall_facing", priority=1,
                  placed_because="entrance shelf"),
    ]

    result = run_with_fallback(placements, MOCK_OBJECTS, sd, brand)
    assert len(result["placed"]) == 1
    assert len(result["dropped"]) == 0
    assert result["fallback_used"] is False
    print(f"  placed: {len(result['placed'])}, dropped: {len(result['dropped'])}")
    print("PASS")


def test_deterministic_fallback():
    """zone에 slot이 없어 실패 -> deterministic fallback으로 다른 zone에 배치."""
    print("\n" + "=" * 60)
    print("TEST: deterministic fallback (zone mismatch)")
    print("=" * 60)

    sd = _make_space_data()
    brand = {"clearspace_mm": {"value": 1500}, "object_pair_rules": []}

    # mid_zone에 shelf 배치 시도 — mid_zone slot은 west_wall 1개뿐
    # + 존재하지 않는 zone에 배치 시도
    placements = [
        Placement(object_type="shelf_3tier", zone_label="entrance_zone",
                  direction="wall_facing", priority=1,
                  placed_because="first"),
        Placement(object_type="shelf_wall", zone_label="entrance_zone",
                  direction="wall_facing", priority=2,
                  placed_because="second"),
        Placement(object_type="display_table", zone_label="entrance_zone",
                  direction="wall_facing", priority=3,
                  placed_because="third — slots exhausted"),
    ]

    result = run_with_fallback(placements, MOCK_OBJECTS, sd, brand)
    print(f"  placed: {len(result['placed'])}, dropped: {len(result['dropped'])}, "
          f"fallback: {result['fallback_used']}, resets: {result['reset_count']}")
    for p in result["placed"]:
        src = p.get("source", "normal")
        print(f"    {p['object_type']} -> {p['slot_key']} (source: {src})")
    for d in result["dropped"]:
        print(f"    DROPPED: {d['object_type']} — {d['reason']}")
    print("PASS")


def test_graceful_degradation():
    """공간이 극도로 작아 모든 오브젝트 실패 -> 드랍."""
    print("\n" + "=" * 60)
    print("TEST: graceful degradation (tiny space)")
    print("=" * 60)

    tiny_poly = Polygon([(0, 0), (1000, 0), (1000, 1000), (0, 1000)])
    sd = {
        "floor": {
            "polygon": tiny_poly,
            "usable_area_sqm": 1.0,
            "max_object_w_mm": 400,
            "ceiling_height_mm": {"value": 3000},
        },
        "fire": {"main_artery": None},
        "dead_zones": [],
        "infra": {"disclaimer": []},
    }
    sd["slot_0"] = {
        "x_mm": 500, "y_mm": 1000,
        "wall_linestring": LineString([(0, 1000), (1000, 1000)]),
        "wall_normal": "north", "zone_label": "entrance_zone",
        "walk_mm": 0, "shelf_capacity": 1,
    }

    brand = {"clearspace_mm": {"value": 1500}, "object_pair_rules": []}

    placements = [
        Placement(object_type="photo_zone_structure", zone_label="entrance_zone",
                  direction="wall_facing", priority=1,
                  placed_because="2000x1500 in 1000x1000 space"),
    ]

    result = run_with_fallback(placements, MOCK_OBJECTS, sd, brand)
    print(f"  placed: {len(result['placed'])}, dropped: {len(result['dropped'])}")
    assert len(result["dropped"]) >= 1, "photo_zone should be dropped in tiny space"
    print("PASS")


if __name__ == "__main__":
    test_all_success()
    test_deterministic_fallback()
    test_graceful_degradation()
    print("\n" + "=" * 60)
    print("ALL P0-5c TESTS PASSED")
    print("=" * 60)
