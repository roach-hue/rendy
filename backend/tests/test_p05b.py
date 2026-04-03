"""
P0-5b 단위 테스트 — placement_engine

실행: cd backend && PYTHONIOENCODING=utf-8 python test_p05b.py
"""
import json
from shapely.geometry import LineString, Point, Polygon

from app.schemas.placement import Placement
from app.modules.placement_engine import run_placement_loop
from app.modules.object_selection import MOCK_OBJECTS


def _make_space_data() -> dict:
    """12000x8000mm 직사각형 공간 + slot 6개 + dead zone 1개."""
    floor_poly = Polygon([(0, 0), (12000, 0), (12000, 8000), (0, 8000)])

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
            "main_artery": LineString([(6000, 8000), (6000, 0)]),
        },
        "dead_zones": [
            Point(3000, 2000).buffer(300),  # sprinkler dead zone
        ],
        "infra": {"disclaimer": []},
    }

    # entrance zone slots (south wall)
    sd["south_wall_slot_0_1"] = {
        "x_mm": 3000, "y_mm": 8000,
        "wall_linestring": LineString([(0, 8000), (12000, 8000)]),
        "wall_normal": "north",
        "zone_label": "entrance_zone",
        "walk_mm": 500, "shelf_capacity": 6,
    }
    sd["south_wall_slot_0_2"] = {
        "x_mm": 9000, "y_mm": 8000,
        "wall_linestring": LineString([(0, 8000), (12000, 8000)]),
        "wall_normal": "north",
        "zone_label": "entrance_zone",
        "walk_mm": 1500, "shelf_capacity": 6,
    }

    # mid zone slots
    sd["west_wall_slot_0_1"] = {
        "x_mm": 0, "y_mm": 4000,
        "wall_linestring": LineString([(0, 0), (0, 8000)]),
        "wall_normal": "east",
        "zone_label": "mid_zone",
        "walk_mm": 5000, "shelf_capacity": 4,
    }
    sd["east_wall_slot_0_1"] = {
        "x_mm": 12000, "y_mm": 4000,
        "wall_linestring": LineString([(12000, 0), (12000, 8000)]),
        "wall_normal": "west",
        "zone_label": "mid_zone",
        "walk_mm": 5000, "shelf_capacity": 4,
    }

    # deep zone slots (north wall)
    sd["north_wall_slot_0_1"] = {
        "x_mm": 3000, "y_mm": 0,
        "wall_linestring": LineString([(0, 0), (12000, 0)]),
        "wall_normal": "south",
        "zone_label": "deep_zone",
        "walk_mm": 9000, "shelf_capacity": 6,
    }
    sd["north_wall_slot_0_2"] = {
        "x_mm": 9000, "y_mm": 0,
        "wall_linestring": LineString([(0, 0), (12000, 0)]),
        "wall_normal": "south",
        "zone_label": "deep_zone",
        "walk_mm": 9500, "shelf_capacity": 6,
    }

    return sd


def test_normal_placement():
    """3 objects, no conflicts."""
    print("\n" + "=" * 60)
    print("TEST: normal placement (3 objects, no conflict)")
    print("=" * 60)

    sd = _make_space_data()
    brand = {
        "clearspace_mm": {"value": 1500, "confidence": "high", "source": "manual"},
        "object_pair_rules": [],
    }

    placements = [
        Placement(object_type="shelf_3tier", zone_label="entrance_zone",
                  direction="wall_facing", priority=1,
                  placed_because="entrance first impression"),
        Placement(object_type="character_hellokitty", zone_label="mid_zone",
                  direction="inward", priority=2,
                  placed_because="mid zone photo point"),
        Placement(object_type="photo_zone_structure", zone_label="deep_zone",
                  direction="wall_facing", priority=3,
                  placed_because="deep zone main attraction"),
    ]

    result = run_placement_loop(placements, MOCK_OBJECTS, sd, brand)
    _print_result(result)

    assert len(result["placed"]) == 3, f"Expected 3 placed, got {len(result['placed'])}"
    assert len(result["failed"]) == 0
    print("PASS")


def test_collision_avoidance():
    """2 objects on same slot -> second should move to next slot."""
    print("\n" + "=" * 60)
    print("TEST: collision avoidance (same zone, 2 objects)")
    print("=" * 60)

    sd = _make_space_data()
    brand = {
        "clearspace_mm": {"value": 1500, "confidence": "high", "source": "manual"},
        "object_pair_rules": [],
    }

    placements = [
        Placement(object_type="shelf_3tier", zone_label="entrance_zone",
                  direction="wall_facing", priority=1,
                  placed_because="first shelf"),
        Placement(object_type="shelf_wall", zone_label="entrance_zone",
                  direction="wall_facing", priority=2,
                  placed_because="second shelf"),
    ]

    result = run_placement_loop(placements, MOCK_OBJECTS, sd, brand)
    _print_result(result)

    assert len(result["placed"]) == 2, f"Expected 2 placed, got {len(result['placed'])}"
    # 두 선반이 다른 slot에 배치되어야 함
    slot_keys = [p["slot_key"] for p in result["placed"]]
    assert slot_keys[0] != slot_keys[1], f"Same slot: {slot_keys}"
    print("PASS")


def test_pair_constraint():
    """kuromi + hellokitty separation rule."""
    print("\n" + "=" * 60)
    print("TEST: pair constraint (kuromi-hellokitty separation)")
    print("=" * 60)

    sd = _make_space_data()
    brand = {
        "clearspace_mm": {"value": 3000, "confidence": "high", "source": "manual"},
        "object_pair_rules": [
            {"rule": "kuromi and hellokitty must be separated by at least 3000mm", "confidence": "high"},
        ],
    }

    # Both in entrance_zone -> slots are 6000mm apart, clearspace 3000mm -> should pass
    placements = [
        Placement(object_type="character_hellokitty", zone_label="entrance_zone",
                  direction="wall_facing", priority=1,
                  placed_because="entrance greeting"),
        Placement(object_type="character_kuromi", zone_label="entrance_zone",
                  direction="wall_facing", priority=2,
                  placed_because="entrance contrast"),
    ]

    result = run_placement_loop(placements, MOCK_OBJECTS, sd, brand)
    _print_result(result)

    assert len(result["placed"]) == 2
    print("PASS")


def test_main_artery_block():
    """Object on Main Artery center (x=6000) should be blocked."""
    print("\n" + "=" * 60)
    print("TEST: Main Artery blocking")
    print("=" * 60)

    sd = _make_space_data()
    # Main artery runs through x=6000. Add a slot right on it.
    sd["center_slot"] = {
        "x_mm": 6000, "y_mm": 4000,
        "wall_linestring": LineString([(0, 4000), (12000, 4000)]),
        "wall_normal": "south",
        "zone_label": "mid_zone",
        "walk_mm": 4500, "shelf_capacity": 2,
    }

    brand = {
        "clearspace_mm": {"value": 1500, "confidence": "high", "source": "manual"},
        "object_pair_rules": [],
    }

    placements = [
        Placement(object_type="display_table", zone_label="mid_zone",
                  direction="wall_facing", priority=1,
                  placed_because="center display"),
    ]

    result = run_placement_loop(placements, MOCK_OBJECTS, sd, brand)
    _print_result(result)

    # center_slot is on artery -> blocked. But west/east wall slots should work.
    placed_slots = [p["slot_key"] for p in result["placed"]]
    assert "center_slot" not in placed_slots, "center_slot should be blocked by Main Artery"
    print("PASS")


def _print_result(result: dict):
    print(f"  placed: {len(result['placed'])}, failed: {len(result['failed'])}")
    for p in result["placed"]:
        print(f"    {p['object_type']} -> {p['slot_key']} "
              f"({p['center_x_mm']}, {p['center_y_mm']}) rot={p['rotation_deg']}")
    for f in result["failed"]:
        print(f"    FAILED: {f['object_type']} — {f['reason']}")


if __name__ == "__main__":
    test_normal_placement()
    test_collision_avoidance()
    test_pair_constraint()
    test_main_artery_block()
    print("\n" + "=" * 60)
    print("ALL P0-5b TESTS PASSED")
    print("=" * 60)
