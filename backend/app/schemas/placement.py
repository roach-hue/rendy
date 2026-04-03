from typing import Literal, Optional
from pydantic import BaseModel, field_validator


class Placement(BaseModel):
    object_type: str
    zone_label: Literal["entrance_zone", "mid_zone", "deep_zone"]
    direction: Literal["wall_facing", "inward", "center", "outward"]
    priority: int
    # Agent 3 자유 회전 — Optional. 없으면 direction 기반 코드 각도 사용.
    # 코드 계산 각도와 15° 미만 차이면 무시됨 (안전장치).
    rotation_deg: Optional[float] = None
    # Agent 3 기획 의도 서사 — 레퍼런스 이미지 참조 허용, mm값 금지
    placed_because: str
    # 코드 전용 — 위치 조정 발생 시 코드가 채움, Agent 3 출력 시 None
    adjustment_log: Optional[str] = None
    # Issue 20 — can_join 쌍에만 사용
    join_with: Optional[str] = None

    @field_validator("placed_because")
    @classmethod
    def no_mm_values_in_narrative(cls, v: str) -> str:
        import re
        if re.search(r"\d+\s*mm", v, re.IGNORECASE):
            raise ValueError("placed_because에 mm 수치 포함 금지 — LLM은 방향만 결정")
        return v

    @field_validator("rotation_deg")
    @classmethod
    def validate_rotation(cls, v: Optional[float]) -> Optional[float]:
        if v is None:
            return None
        # 직교 각도(0, 90, 180, 270)로 snap — LLM 임의 각도 방어
        ORTHO = [0, 90, 180, 270]
        normalized = v % 360
        snapped = min(ORTHO, key=lambda o: abs(((normalized - o + 540) % 360) - 180))
        return float(snapped)

    @field_validator("direction")
    @classmethod
    def outward_is_dummy(cls, v: str) -> str:
        # outward는 더미 처리 — 실제 케이스 없음
        return v
