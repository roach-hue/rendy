from typing import Optional
from pydantic import BaseModel, field_validator


class DetectedPoint(BaseModel):
    x_px: float
    y_px: float
    confidence: str


class DetectedLineSegment(BaseModel):
    start_px: tuple[float, float]
    end_px: tuple[float, float]
    confidence: str


class DetectedPolygon(BaseModel):
    polygon_px: list[tuple[float, float]]
    confidence: str


class ParsedFloorPlan(BaseModel):
    """평면도(floor plan) 파싱 결과. space_data["floor"]와 구분할 것."""
    floor_polygon_px: list[tuple[float, float]]
    scale_mm_per_px: float
    # Vision 추정 성공 시 True, fallback(10.0) 시 False → UI에서 사용자 확인 필요
    scale_confirmed: bool = False
    # Vision이 읽은 건물 치수 (도면 텍스트에서 추출)
    detected_width_mm: Optional[float] = None
    detected_height_mm: Optional[float] = None
    entrance: Optional[DetectedPoint] = None
    # 입구 개구부 폭 (mm). 파서가 추출, 없으면 agent2에서 2000mm 기본값 사용.
    entrance_width_mm: Optional[float] = None
    sprinklers: list[DetectedPoint] = []
    fire_hydrant: list[DetectedPoint] = []
    electrical_panel: list[DetectedPoint] = []
    inner_walls: list[DetectedLineSegment] = []
    inaccessible_rooms: list[DetectedPolygon] = []


class ParsedSection(BaseModel):
    """단면도(section drawing) 파싱 결과. 없으면 None → DEFAULTS에서 3000mm 적용."""
    ceiling_height_mm: Optional[float] = None

    @field_validator("ceiling_height_mm")
    @classmethod
    def check_height_range(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and not (1800 <= v <= 10000):
            raise ValueError(f"ceiling_height_mm 비정상 범위: {v}mm (허용: 1800~10000)")
        return v


class ParsedDrawings(BaseModel):
    """
    Issue 22 — 평면도 + 단면도 통합 스키마. 모든 파서 어댑터의 공통 출력.

    명칭 구분:
      floor_plan  → ParsedFloorPlan  : 평면도 파싱 결과 (픽셀 좌표계)
      section     → ParsedSection    : 단면도 파싱 결과 (ceiling_height_mm 등)
      space_data["floor"]            : Agent 2 후반부가 mm 변환 후 확정한 공간 데이터 (별개)
    """
    floor_plan: ParsedFloorPlan
    section: Optional[ParsedSection] = None
