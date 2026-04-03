"""
오브젝트 선별 모듈 — 순수 코드, LLM 없음

Supabase furniture_standards 테이블에서 brand_id로 조회 후
공간 제약 + 브랜드 금지 소재 필터링.
"""
import os
from supabase import create_client


def _get_supabase():
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")
    if not url or not key:
        raise RuntimeError("SUPABASE_URL / SUPABASE_KEY 환경변수 없음")
    return create_client(url, key)


def select_eligible_objects(
    space_data: dict,
    brand_data: dict,
    brand_id: str = "sanrio",
) -> list[dict]:
    """
    Supabase에서 오브젝트 조회 → 공간 제약 + 브랜드 금지 소재 필터링.
    빈 목록이면 ValueError.
    """
    # Step 1: Supabase 조회
    client = _get_supabase()
    try:
        r = client.table("furniture_standards") \
            .select("object_type, width_mm, depth_mm, height_mm, category, material, can_join, overlap_margin_mm") \
            .eq("brand_id", brand_id) \
            .execute()
        objects = r.data
        print(f"[ObjectSelection] Supabase query brand_id='{brand_id}': {len(objects)} rows")
    except Exception as e:
        print(f"[ObjectSelection] Supabase query failed: {e}")
        # brand_id 미매칭 시 generic fallback
        try:
            r = client.table("furniture_standards") \
                .select("object_type, width_mm, depth_mm, height_mm, category, material, can_join, overlap_margin_mm") \
                .eq("brand_id", "generic") \
                .execute()
            objects = r.data
            print(f"[ObjectSelection] fallback to generic: {len(objects)} rows")
        except Exception as e2:
            raise RuntimeError(f"Supabase 조회 실패: {e2}")

    if not objects:
        # generic fallback
        r = client.table("furniture_standards") \
            .select("object_type, width_mm, depth_mm, height_mm, category, material, can_join, overlap_margin_mm") \
            .eq("brand_id", "generic") \
            .execute()
        objects = r.data
        print(f"[ObjectSelection] no rows for '{brand_id}', fallback to generic: {len(objects)} rows")

    floor = space_data.get("floor", {})
    max_w = floor.get("max_object_w_mm", float("inf"))
    ceiling_h_field = floor.get("ceiling_height_mm", {})
    ceiling_h = ceiling_h_field.get("value", 3000) if isinstance(ceiling_h_field, dict) else 3000

    print(f"[ObjectSelection] filter: max_w={max_w}mm, ceiling_h={ceiling_h}mm")

    # Step 2: 공간 제약 필터
    eligible = []
    for obj in objects:
        if obj["width_mm"] > max_w:
            print(f"[ObjectSelection] SKIP {obj['object_type']}: width {obj['width_mm']} > max {max_w}")
            continue
        if obj["height_mm"] > ceiling_h:
            print(f"[ObjectSelection] SKIP {obj['object_type']}: height {obj['height_mm']} > ceiling {ceiling_h}")
            continue
        eligible.append(obj)

    # Step 3: 브랜드 금지 소재 필터
    prohibited = brand_data.get("prohibited_material", {})
    prohibited_val = prohibited.get("value") if isinstance(prohibited, dict) else None

    if prohibited_val:
        before = len(eligible)
        eligible = [
            obj for obj in eligible
            if prohibited_val.lower() not in obj.get("material", "").lower()
        ]
        print(f"[ObjectSelection] prohibited material '{prohibited_val}': {before} -> {len(eligible)}")

    print(f"[ObjectSelection] eligible: {len(eligible)} objects -> "
          f"{[o['object_type'] for o in eligible]}")

    if not eligible:
        raise ValueError("배치 가능한 오브젝트 없음")

    return eligible
