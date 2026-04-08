from typing import Literal, Optional
from pydantic import BaseModel, field_validator


class Placement(BaseModel):
    object_type: str
    zone_label: Literal["entrance_zone", "mid_zone", "deep_zone"]
    direction: Literal["wall_facing", "inward", "center", "outward"]
    priority: int
    # 벽면 대비 기물 정렬 방식 — LLM이 기하학적 의도만 선택, 실제 각도는 코드가 계산
    alignment: Literal["parallel", "perpendicular", "opposite", "none"] = "parallel"
    # Agent 3 기획 의도 서사 — 레퍼런스 이미지 참조 허용, mm값 금지
    placed_because: str
    # 코드 전용 — 위치 조정 발생 시 코드가 채움, Agent 3 출력 시 None
    adjustment_log: Optional[str] = None
    # Issue 20 — can_join 쌍에만 사용
    join_with: Optional[str] = None
    # Agent 4 개방형 필드 — Agent 3은 비워두거나 기본값. Agent 4가 덮어씀.
    style_hint: Optional[str] = None        # "모던", "클래식", "팝" 등 스타일 키워드
    cluster_group: Optional[str] = None     # 군집 그룹 ID (같은 그룹은 인접 배치)
    focal_weight: Optional[float] = None    # 0.0~1.0 시선 집중도 가중치

    @field_validator("placed_because")
    @classmethod
    def strip_mm_values_from_narrative(cls, v: str) -> str:
        """mm 수치를 에러 대신 자동 제거 — Circuit Breaker 낭비 방지."""
        import re
        cleaned = re.sub(r"\d+\s*mm", "", v, flags=re.IGNORECASE).strip()
        if cleaned != v:
            print(f"[Placement] placed_because에서 mm 수치 자동 제거: {v[:80]}")
        return cleaned if cleaned else "배치 기획 의도"

    @field_validator("direction")
    @classmethod
    def outward_is_dummy(cls, v: str) -> str:
        return v
