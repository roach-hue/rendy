"""
오브젝트 선별 모듈 — 순수 코드, LLM 없음

Supabase furniture_standards 테이블에서 brand_id로 조회 후
공간 제약 + 브랜드 금지 소재 필터링.
"""
from app.api.supabase_client import get_client as _get_supabase


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

    # Step 4: IQI — 면적 기반 수량 추론
    usable_area_mm2 = floor.get("usable_area_sqm", 100) * 1_000_000  # m² → mm²
    eligible = _apply_iqi(eligible, usable_area_mm2)

    print(f"[ObjectSelection] eligible: {len(eligible)} objects -> "
          f"{[o['object_type'] for o in eligible]}")

    if not eligible:
        raise ValueError("배치 가능한 오브젝트 없음")

    return eligible


# ── IQI: Intelligent Quantity Inference ──────────────────────────────────────

# 유효 면적 대비 최대 기물 점유율 (25%)
MAX_DENSITY_RATIO = 0.25

# 기물 우선순위 (높을수록 우선 배치, DB에 priority_score 컬럼 추가 전까지 하드코딩)
_PRIORITY_SCORE: dict[str, int] = {
    "display_table": 90,
    "photo_zone_structure": 85,
    "character_hellokitty": 80,
    "character_kuromi": 80,
    "character_mymelody": 80,
    "shelf_3tier": 70,
    "shelf_wall": 65,
    "shelf_standard": 60,
    "banner_stand": 50,
    "banner_standard": 45,
    "pos_counter": 95,
    "display_table_standard": 88,
}


def _apply_iqi(
    eligible: list[dict],
    usable_area_mm2: float,
) -> list[dict]:
    """
    IQI 엔진: 면적 밀도 제약 기반 수량 추론.

    Step 1: 유효 면적 × MAX_DENSITY_RATIO = 최대 점유 가능 면적
    Step 2: priority_score 내림차순 정렬
    Step 3: 누적 면적이 한도 초과 시 이후 기물 제거
    """
    max_footprint = usable_area_mm2 * MAX_DENSITY_RATIO

    # priority_score로 정렬 (높을수록 우선)
    scored = sorted(
        eligible,
        key=lambda o: _PRIORITY_SCORE.get(o["object_type"], 40),
        reverse=True,
    )

    accepted: list[dict] = []
    cumulative_area = 0.0
    dropped_count = 0

    for obj in scored:
        footprint = obj["width_mm"] * obj["depth_mm"]
        if cumulative_area + footprint > max_footprint:
            dropped_count += 1
            continue
        cumulative_area += footprint
        accepted.append(obj)

    occupancy_pct = (cumulative_area / usable_area_mm2 * 100) if usable_area_mm2 > 0 else 0
    print(f"[IQI] usable={usable_area_mm2/1_000_000:.1f}m², "
          f"max_footprint={max_footprint/1_000_000:.1f}m² ({MAX_DENSITY_RATIO*100:.0f}%), "
          f"accepted={len(accepted)}, dropped={dropped_count}, "
          f"occupancy={occupancy_pct:.1f}%")

    return accepted
