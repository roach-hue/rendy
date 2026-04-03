"""
검증 결과 + 요약 리포트 Pydantic 스키마.
verification.py → VerificationResult 반환.
routes.py → SummaryReport 생성.
"""
from pydantic import BaseModel


class ViolationItem(BaseModel):
    object_type: str
    rule: str       # "floor_exit" | "dead_zone" | "main_artery" | "corridor" | "wall_clearance"
    severity: str   # "blocking" | "warning"
    detail: str     # "기물 A와 B 사이 간격 750mm로 규정 미달"


class VerificationResult(BaseModel):
    passed: bool
    blocking: list[ViolationItem]
    warning: list[ViolationItem]
    checked_count: int


class SummaryReport(BaseModel):
    total_area_sqm: float
    zone_distribution: dict[str, int]
    placed_count: int
    dropped_count: int
    success_rate: float
    fallback_used: bool
    slot_count: int
    verification_passed: bool
