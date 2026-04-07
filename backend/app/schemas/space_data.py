"""
space_data: 전체 파이프라인의 단일 Python dict 저장소.

구조 참조: architecture_spec.md ## space_data 구조
런타임에는 일반 dict로 사용. 이 파일은 키 구조 문서화 + 헬퍼 함수 제공.
NetworkX 그래프 객체는 dict에 저장 금지 — 함수 내 변수로만 유지.
"""
from typing import Any, TypedDict


class PlacementSlotData(TypedDict):
    x_mm: float
    y_mm: float
    # Shapely LineString (직렬화 불가 — 런타임 전용)
    wall_linestring: Any
    wall_normal: str                    # "north" | "south" | "east" | "west"
    zone_label: str                     # Agent 3용 자연어
    shelf_capacity: int
    walk_mm: float                      # NetworkX 보행 거리


class ZoneThresholdData(TypedDict):
    walk_mm_min: float
    walk_mm_max: float                  # deep_zone은 float("inf")


class FireData(TypedDict):
    main_corridor_min_mm: float         # 900
    emergency_path_min_mm: float        # 1200
    # Shapely LineString 캐시 — Issue 19. Global Reset 후에도 유지
    main_artery: Any


class ConstructionData(TypedDict):
    wall_clearance_mm: float            # 300


class FloorData(TypedDict):
    # Shapely Polygon (런타임 전용)
    polygon: Any
    usable_area_sqm: float
    max_object_w_mm: float
    # Issue 22 — 단면도 추출, 없으면 DEFAULTS에서 3000mm 적용
    # 구조: {"value": 3000, "confidence": "low", "source": "default"}
    ceiling_height_mm: dict


def make_empty_space_data() -> dict:
    """파이프라인 시작 시 빈 space_data 초기화."""
    return {
        "floor": {},
        "zones": {
            "entrance_zone": {"walk_mm_min": 0,   "walk_mm_max": 400},
            "mid_zone":      {"walk_mm_min": 400, "walk_mm_max": 700},
            "deep_zone":     {"walk_mm_min": 700, "walk_mm_max": float("inf")},
        },
        "brand": {},
        "fire": {
            "main_corridor_min_mm": 900,
            "emergency_path_min_mm": 1200,
            "main_artery": None,
        },
        "construction": {
            "wall_clearance_mm": 300,
        },
        "infra": {
            "disclaimer": [],
        },
        # placement_slot들은 동적으로 추가됨
        # 예: space_data["north_wall_mid"] = PlacementSlotData(...)
    }


def extract_slots(space_data: dict) -> dict[str, dict]:
    """space_data에서 배치 슬롯만 추출. 7곳에서 반복되던 필터 로직 통합."""
    return {
        k: v for k, v in space_data.items()
        if isinstance(v, dict) and "zone_label" in v and k != "floor"
    }


def assign_zone_by_walk_mm(walk_mm: float, zones: dict) -> str:
    """walk_mm 값으로 zone_label 반환. Agent 3 출력 2차 검증에 사용."""
    for zone_label, threshold in zones.items():
        if threshold["walk_mm_min"] <= walk_mm < threshold["walk_mm_max"]:
            return zone_label
    return "deep_zone"
