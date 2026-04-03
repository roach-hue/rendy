from typing import Any, Literal, Optional
from pydantic import BaseModel, field_validator


class BrandField(BaseModel):
    value: Any
    confidence: Literal["high", "medium", "low"]
    source: Literal["manual", "default", "user_corrected", "fallback"]


class RelationshipRule(BaseModel):
    rule: str
    confidence: Literal["high", "medium", "low"]


class BrandData(BaseModel):
    clearspace_mm: Optional[BrandField] = None
    character_orientation: Optional[BrandField] = None
    prohibited_material: Optional[BrandField] = None
    logo_clearspace_mm: Optional[BrandField] = None
    object_pair_rules: list[RelationshipRule] = []

    @field_validator("clearspace_mm")
    @classmethod
    def check_clearspace_range(cls, v: Optional[BrandField]) -> Optional[BrandField]:
        if v is not None and v.value is not None:
            if not (300 <= v.value <= 5000):
                raise ValueError(f"clearspace_mm 비정상 범위: {v.value}mm (허용: 300~5000)")
        return v

    @field_validator("logo_clearspace_mm")
    @classmethod
    def check_logo_clearspace_range(cls, v: Optional[BrandField]) -> Optional[BrandField]:
        if v is not None and v.value is not None:
            if not (50 <= v.value <= 3000):
                raise ValueError(f"logo_clearspace_mm 비정상 범위: {v.value}mm (허용: 50~3000)")
        return v
