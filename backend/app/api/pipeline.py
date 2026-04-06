"""
파이프라인 오케스트레이터 — 전체 배치 파이프라인 조율.
Agent 2 → Object Selection → Agent 3 → Placement Engine → Verification → Report → GLB
"""
import base64
import traceback

from app.agents.agent2_back import run as run_agent2
from app.agents.agent3_placement import plan_placement
from app.modules.object_selection import select_eligible_objects
from app.modules.failure_handler import run_with_fallback
from app.modules.verification import verify_placement
from app.modules.report_generator import generate_report
from app.modules.glb_exporter import export_glb
from app.schemas.drawings import ParsedDrawings
from app.schemas.verification import SummaryReport


import hashlib
import json as _json
import time
from pathlib import Path

# 배치 결과 캐시 (동일 도면 → LLM 0회)
_PLACEMENT_CACHE_DIR = Path(__file__).parent.parent.parent / "cache" / "placement"
_PLACEMENT_CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _compute_drawings_hash(drawings_json: dict, scale: float) -> str:
    """도면 + 스케일 해시 → 캐시 키."""
    fp = drawings_json.get("floor_plan", {})
    key = f"{fp.get('floor_polygon_px', [])}:{scale}"
    return hashlib.md5(key.encode()).hexdigest()[:12]


def run_placement_pipeline(
    drawings_json: dict,
    brand_data: dict,
    scale_mm_per_px: float,
) -> dict:
    """
    전체 배치 파이프라인 실행.
    동일 도면(polygon+scale 95% 일치) → 캐시 히트 시 LLM 0회, 0.1초 응답.
    """
    t0 = time.time()
    cache_key = _compute_drawings_hash(drawings_json, scale_mm_per_px)
    cache_file = _PLACEMENT_CACHE_DIR / f"{cache_key}.json"

    # 캐시 히트 → LLM 0회
    if cache_file.exists():
        try:
            cached = _json.loads(cache_file.read_text(encoding="utf-8"))
            elapsed = time.time() - t0
            print(f"[Pipeline] CACHE HIT: {cache_key} → {elapsed:.2f}s (LLM 0회)")
            return cached
        except Exception as e:
            print(f"[Pipeline] cache read failed: {e} — full pipeline")

    print("[Pipeline] placement request received (cache miss)")
    drawings = ParsedDrawings.model_validate(drawings_json)
    sd = run_agent2(drawings=drawings, scale_mm_per_px=scale_mm_per_px)

    eligible = select_eligible_objects(sd, brand_data)
    print(f"[Pipeline] eligible objects: {len(eligible)}")

    placements = plan_placement(eligible, sd, brand_data)
    print(f"[Pipeline] Agent 3 placements: {len(placements)}")

    # GAP: Agent 3이 제안한 기물 중 DB에 없는 것 → furniture_standards에 INSERT
    eligible = _provision_missing_assets(placements, eligible, brand_data)

    result = run_with_fallback(
        placements, eligible, sd, brand_data,
        plan_fn=plan_placement,
    )
    print(f"[Pipeline] placed: {len(result['placed'])}, dropped: {len(result['dropped'])}")

    verification = verify_placement(result["placed"], sd)

    report = generate_report(
        result["placed"], result["dropped"], verification.model_dump(),
        sd, brand_data, result["fallback_used"],
    )

    glb_bytes = export_glb(result["placed"], sd)
    glb_b64 = base64.b64encode(glb_bytes).decode()

    summary = _build_summary(
        sd, result["placed"], result["dropped"],
        result["fallback_used"], verification,
    )

    # 3D 바닥 동선 시각화용 데이터
    # CRITICAL: main_artery 길이 추적
    _artery = sd.get("fire", {}).get("main_artery")
    if _artery and hasattr(_artery, "coords"):
        _ac = list(_artery.coords)
        print(f"[CRITICAL] main_artery BEFORE floor_viz: {len(_ac)} nodes, "
              f"start=({_ac[0][0]:.0f},{_ac[0][1]:.0f}), end=({_ac[-1][0]:.0f},{_ac[-1][1]:.0f})")
    else:
        print(f"[CRITICAL] main_artery BEFORE floor_viz: {type(_artery)} (missing or stripped!)")

    floor_viz = _build_floor_viz(sd)
    print(f"[CRITICAL] floor_viz.main_artery: {len(floor_viz.get('main_artery', []))} nodes")

    from app.api.serializer import strip_shapely
    response = strip_shapely({
        "placed": result["placed"],
        "dropped": result["dropped"],
        "verification": verification.model_dump(),
        "report": report,
        "glb_base64": glb_b64,
        "log": result["log"],
        "summary": summary.model_dump(),
        "floor_viz": floor_viz,
    })

    # 배치 결과 캐시 저장
    try:
        cache_file.write_text(_json.dumps(response, ensure_ascii=False), encoding="utf-8")
        elapsed = time.time() - t0
        print(f"[Pipeline] CACHE SAVE: {cache_key} ({elapsed:.1f}s)")
    except Exception as e:
        print(f"[Pipeline] cache save failed: {e}")

    return response


def run_space_data(drawings: ParsedDrawings, scale: float, entrance_px=None, user_dims=None):
    """Agent 2 후반부 실행 + 직렬화."""
    from app.agents.agent2_back import run

    if user_dims:
        drawings = _rebuild_polygon(drawings, user_dims, scale)

    sd = run(drawings=drawings, scale_mm_per_px=scale, user_entrance_px=entrance_px)

    from app.api.serializer import strip_shapely
    return strip_shapely(sd)


def _rebuild_polygon(drawings, user_dims, scale):
    fp = drawings.floor_plan
    xs = [p[0] for p in fp.floor_polygon_px]
    ys = [p[1] for p in fp.floor_polygon_px]
    cx = (min(xs) + max(xs)) / 2
    cy = (min(ys) + max(ys)) / 2
    half_w = (user_dims["width_mm"] / scale) / 2
    half_h = (user_dims["height_mm"] / scale) / 2

    new_polygon = [
        (cx - half_w, cy - half_h), (cx + half_w, cy - half_h),
        (cx + half_w, cy + half_h), (cx - half_w, cy + half_h),
    ]
    new_fp = fp.model_copy(update={"floor_polygon_px": new_polygon})
    return drawings.model_copy(update={"floor_plan": new_fp})


def _provision_missing_assets(
    placements,
    eligible: list[dict],
    brand_data: dict,
    brand_id: str = "sanrio",
) -> list[dict]:
    """
    Generative Asset Provisioning:
    Agent 3이 제안한 기물 중 eligible에 없는 것을 DB에 INSERT하고 eligible에 추가.
    """
    eligible_types = {o["object_type"] for o in eligible}
    missing = []

    for p in placements:
        if p.object_type not in eligible_types:
            missing.append(p.object_type)
            eligible_types.add(p.object_type)  # 중복 방지

    if not missing:
        return eligible

    # 미등록 기물 → 기본 규격으로 생성 + DB INSERT
    import os
    DEFAULT_SPECS = {
        "character":  {"width_mm": 800, "depth_mm": 150, "height_mm": 2000, "category": "character", "material": "FRP"},
        "shelf":      {"width_mm": 1200, "depth_mm": 400, "height_mm": 1200, "category": "shelf", "material": "wood_painted"},
        "display":    {"width_mm": 1200, "depth_mm": 600, "height_mm": 800, "category": "display", "material": "wood_painted"},
        "photo":      {"width_mm": 2000, "depth_mm": 200, "height_mm": 2400, "category": "photo_zone", "material": "FRP"},
        "banner":     {"width_mm": 600, "depth_mm": 100, "height_mm": 2000, "category": "signage", "material": "fabric_metal_frame"},
        "pos":        {"width_mm": 800, "depth_mm": 600, "height_mm": 1000, "category": "counter", "material": "wood_painted"},
    }

    new_assets = []
    for obj_type in missing:
        # 카테고리 키워드 매칭으로 기본 규격 결정
        spec = DEFAULT_SPECS.get("character")  # fallback
        for keyword, s in DEFAULT_SPECS.items():
            if keyword in obj_type.lower():
                spec = s
                break

        asset = {
            "object_type": obj_type,
            "brand_id": brand_id,
            **spec,
            "can_join": False,
            "overlap_margin_mm": 0,
        }
        new_assets.append(asset)
        eligible.append(asset)
        print(f"[GAP] Provisioned: {obj_type} → {spec['width_mm']}x{spec['depth_mm']}x{spec['height_mm']}mm ({spec['category']})")

    # Supabase DB INSERT (영속화)
    try:
        url = os.getenv("SUPABASE_URL")
        key = os.getenv("SUPABASE_KEY")
        if url and key:
            from supabase import create_client
            client = create_client(url, key)
            for asset in new_assets:
                row = {
                    "object_type": asset["object_type"],
                    "brand_id": asset["brand_id"],
                    "width_mm": asset["width_mm"],
                    "depth_mm": asset["depth_mm"],
                    "height_mm": asset["height_mm"],
                    "category": asset["category"],
                    "material": asset["material"],
                }
                client.table("furniture_standards").insert(row).execute()
                print(f"[GAP] DB INSERT: {asset['object_type']} → furniture_standards")
    except Exception as e:
        print(f"[GAP] DB INSERT failed: {e} — in-memory only")

    print(f"[GAP] Total provisioned: {len(new_assets)} new assets")
    return eligible


def _build_floor_viz(space_data: dict) -> dict:
    """3D 바닥 동선 시각화용 데이터 추출."""
    # slot별 walk_mm + zone_label + 좌표
    slots = []
    for key, val in space_data.items():
        if isinstance(val, dict) and "zone_label" in val and key != "floor":
            slots.append({
                "x_mm": val.get("x_mm", 0),
                "y_mm": val.get("y_mm", 0),
                "walk_mm": val.get("walk_mm", 0),
                "zone_label": val.get("zone_label", "unknown"),
            })

    # Main Artery 좌표 리스트
    main_artery_coords = []
    artery = space_data.get("fire", {}).get("main_artery")
    if artery and hasattr(artery, "coords"):
        main_artery_coords = [
            [round(x, 1), round(y, 1)] for x, y in artery.coords
        ]

    # walk_mm 범위 (그라데이션용)
    walk_values = [s["walk_mm"] for s in slots] if slots else [0]
    max_walk = max(walk_values) if walk_values else 1

    return {
        "slots": slots,
        "main_artery": main_artery_coords,
        "max_walk_mm": max_walk,
    }


def _build_summary(space_data, placed, dropped, fallback_used, verification):
    floor = space_data.get("floor", {})
    zone_dist: dict[str, int] = {}
    for p in placed:
        z = p.get("zone_label", "unknown")
        zone_dist[z] = zone_dist.get(z, 0) + 1

    slot_count = sum(
        1 for k, v in space_data.items()
        if isinstance(v, dict) and "zone_label" in v and k != "floor"
    )
    total = len(placed) + len(dropped)

    return SummaryReport(
        total_area_sqm=floor.get("usable_area_sqm", 0),
        zone_distribution=zone_dist,
        placed_count=len(placed),
        dropped_count=len(dropped),
        success_rate=round(len(placed) / total, 3) if total > 0 else 0.0,
        fallback_used=fallback_used,
        slot_count=slot_count,
        verification_passed=verification.passed,
    )
