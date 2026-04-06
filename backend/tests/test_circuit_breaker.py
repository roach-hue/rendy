"""Circuit Breaker 발동 테스트 — slot은 있지만 Agent 3이 매번 같은 실패 기획을 반복."""
import json, os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

from shapely.geometry import Polygon, LineString, Point
from app.schemas.placement import Placement
from app.modules.failure_handler import run_with_fallback

# 공간: 5000x5000mm, slot 2개, Dead Zone이 slot 근처를 막아서 cascade 유발
floor = Polygon([(0,0),(5000,0),(5000,5000),(0,5000)])
# Dead Zone: slot 근처를 막음 (cascade trigger)
dead_zone = Point(2500, 200).buffer(800)

space_data = {
    "floor": {"polygon": floor, "usable_area_sqm": 25.0, "max_object_w_mm": 2000},
    "dead_zones": [dead_zone],
    "fire": {"main_corridor_min_mm": 900, "emergency_path_min_mm": 1200, "main_artery": None},
    "construction": {"wall_clearance_mm": 300},
    "_origin_offset_mm": (0, 0),
    # slot 2개 (벽면)
    "south_wall_slot_0_1": {
        "x_mm": 2500, "y_mm": 5000,
        "wall_linestring": LineString([(0,5000),(5000,5000)]),
        "wall_normal": "north", "wall_normal_vec": (0.0, -1.0), "wall_angle_deg": 0.0,
        "zone_label": "entrance_zone", "shelf_capacity": 2, "walk_mm": 500,
    },
    "south_wall_slot_1_1": {
        "x_mm": 2500, "y_mm": 0,
        "wall_linestring": LineString([(0,0),(5000,0)]),
        "wall_normal": "south", "wall_normal_vec": (0.0, 1.0), "wall_angle_deg": 180.0,
        "zone_label": "deep_zone", "shelf_capacity": 2, "walk_mm": 4500,
    },
}

eligible = [
    {"object_type": "big_object_a", "category": "display", "width_mm": 2000, "depth_mm": 1500, "height_mm": 1000, "can_join": False},
    {"object_type": "big_object_b", "category": "display", "width_mm": 2000, "depth_mm": 1500, "height_mm": 1000, "can_join": False},
    {"object_type": "big_object_c", "category": "display", "width_mm": 2000, "depth_mm": 1500, "height_mm": 1000, "can_join": False},
]

# Agent 3 mock: 항상 같은 기획 반복 → cascade 반복 → circuit breaker
call_count = 0
def mock_plan_same_fail(eligible_objs, sd, bd, feedback=""):
    global call_count
    call_count += 1
    print(f"[MockAgent3] retry #{call_count}")
    return [
        Placement(object_type="big_object_a", zone_label="entrance_zone", direction="center",
                  priority=1, placed_because="test"),
        Placement(object_type="big_object_b", zone_label="entrance_zone", direction="center",
                  priority=2, placed_because="test"),
        Placement(object_type="big_object_c", zone_label="entrance_zone", direction="center",
                  priority=3, placed_because="test"),
    ]

initial = [
    Placement(object_type="big_object_a", zone_label="entrance_zone", direction="center",
              priority=1, placed_because="test"),
    Placement(object_type="big_object_b", zone_label="entrance_zone", direction="center",
              priority=2, placed_because="test"),
    Placement(object_type="big_object_c", zone_label="entrance_zone", direction="center",
              priority=3, placed_because="test"),
]

print("=" * 60)
print("Circuit Breaker Test")
print("=" * 60)

result = run_with_fallback(initial, eligible, space_data, {}, plan_fn=mock_plan_same_fail)

print()
print("=" * 60)
print(f"placed={len(result['placed'])}, dropped={len(result['dropped'])}, retries={result['reset_count']}")
print(f"MockAgent3 calls: {call_count}")
if call_count >= 3:
    print("Circuit Breaker: TRIGGERED")
elif call_count > 0:
    print(f"Retries: {call_count} (under limit)")
else:
    print("No retries triggered")
