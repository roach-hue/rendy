"""
E2E Pipeline Test — All-Active 원칙.

현재 등록된 모든 에이전트를 동적으로 포함하여 전체 워크플로우 실행.
각 단계 실패 시 breakpoint 명시.
Agent 추가 시 PIPELINE_STAGES에 등록만 하면 자동 확장.
"""
import json
import base64
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")


# ── 파이프라인 스테이지 레지스트리 ─────────────────────────────────────────────
# Agent/모듈 추가 시 여기에 등록. 순서 = 실행 순서.
# 각 스테이지: (이름, 실행 함수, 의존 입력 키)

def _stage_cache_load(ctx):
    cache_file = Path(__file__).parent.parent / "cache" / "last_session.json"
    cache = json.loads(cache_file.read_text(encoding="utf-8", errors="replace"))
    ctx["drawings"] = cache["drawings"]
    ctx["brand_data"] = cache.get("brand_data", {})
    ctx["scale"] = cache.get("scale_mm_per_px", 10.0)
    return "Cache loaded"


def _stage_agent1_brand(ctx):
    # Agent 1은 캐시에 brand_data로 이미 포함. 실서비스에서는 PDF → extract.
    if ctx["brand_data"]:
        return f"brand_data loaded ({len(ctx['brand_data'])} keys)"
    return "brand_data empty (no manual provided)"


def _stage_agent2_space(ctx):
    from app.schemas.drawings import ParsedDrawings
    from app.agents.agent2_back import run as run_agent2
    drawings = ParsedDrawings.model_validate(ctx["drawings"])
    ctx["space_data"] = run_agent2(drawings=drawings, scale_mm_per_px=ctx["scale"])
    slot_count = sum(1 for k, v in ctx["space_data"].items()
                     if isinstance(v, dict) and "zone_label" in v and k != "floor")
    ctx["slot_count"] = slot_count
    return f"{slot_count} slots"


def _stage_object_selection(ctx):
    from app.modules.object_selection import select_eligible_objects
    ctx["eligible"] = select_eligible_objects(ctx["space_data"], ctx["brand_data"])
    return f"{len(ctx['eligible'])} eligible"


def _stage_agent3_planning(ctx):
    from app.agents.agent3_placement import plan_placement
    ctx["placements"] = plan_placement(ctx["eligible"], ctx["space_data"], ctx["brand_data"])
    ctx["plan_fn"] = plan_placement
    return f"{len(ctx['placements'])} placements (max_slots={ctx['slot_count']})"


def _stage_placement_engine(ctx):
    from app.modules.failure_handler import run_with_fallback
    result = run_with_fallback(
        ctx["placements"], ctx["eligible"], ctx["space_data"], ctx["brand_data"],
        plan_fn=ctx.get("plan_fn"),
    )
    ctx["result"] = result
    ctx["placed"] = result["placed"]
    ctx["dropped"] = result["dropped"]
    return f"{len(result['placed'])} placed, {len(result['dropped'])} dropped"


def _stage_verification(ctx):
    from app.modules.verification import verify_placement
    ctx["verification"] = verify_placement(ctx["placed"], ctx["space_data"])
    v = ctx["verification"]
    return f"{'PASS' if v.passed else 'FAIL'} ({len(v.blocking)} blocking, {len(v.warning)} warning)"


def _stage_agent5_report(ctx):
    from app.modules.report_generator import generate_report
    ctx["report"] = generate_report(
        ctx["placed"], ctx["dropped"], ctx["verification"].model_dump(),
        ctx["space_data"], ctx["brand_data"], ctx["result"]["fallback_used"],
    )
    return f"{len(ctx['report'])} chars"


def _stage_glb_export(ctx):
    from app.modules.glb_exporter import export_glb
    glb_bytes = export_glb(ctx["placed"], ctx["space_data"])
    ctx["glb_bytes"] = glb_bytes
    ctx["glb_b64"] = base64.b64encode(glb_bytes).decode()
    return f"{len(glb_bytes)} bytes"


# ── 스테이지 등록 (순서 = 파이프라인 실행 순서) ──────────────────────────────
# Agent 4 추가 시: ("Agent 4 (Style)", _stage_agent4_style) 를 여기에 추가
PIPELINE_STAGES = [
    ("Cache Load",          _stage_cache_load),
    ("Agent 1 (Brand)",     _stage_agent1_brand),
    ("Agent 2 (Space)",     _stage_agent2_space),
    ("Object Selection",    _stage_object_selection),
    ("Agent 3 (Planning)",  _stage_agent3_planning),
    ("Placement Engine",    _stage_placement_engine),
    ("Verification",        _stage_verification),
    ("Agent 5 (Report)",    _stage_agent5_report),
    ("GLB Export",          _stage_glb_export),
]


def main():
    print("=" * 60)
    print(f"E2E Pipeline Test — All-Active ({len(PIPELINE_STAGES)} stages)")
    print("=" * 60)

    ctx: dict = {}
    breakpoint_stage = None

    for i, (name, fn) in enumerate(PIPELINE_STAGES, 1):
        try:
            result_msg = fn(ctx)
            print(f"[{i}/{len(PIPELINE_STAGES)}] {name}: {result_msg}")
        except Exception as e:
            breakpoint_stage = name
            print(f"[{i}/{len(PIPELINE_STAGES)}] {name}: FAILED — {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()
            break

    # ── 결과 요약 ────────────────────────────────────────────────────────────
    print()
    print("=" * 60)
    print("E2E RESULT")
    print("=" * 60)

    if breakpoint_stage:
        print(f"  Breakpoint:   {breakpoint_stage}")
        print(f"  Status:       FAIL — pipeline broke at '{breakpoint_stage}'")
        print()
        print("E2E FAIL")
        return

    placed = ctx.get("placed", [])
    dropped = ctx.get("dropped", [])
    placements = ctx.get("placements", [])
    verification = ctx.get("verification")
    report = ctx.get("report", "")
    glb_bytes = ctx.get("glb_bytes", b"")
    result = ctx.get("result", {})

    total = len(placed) + len(dropped)
    success_rate = len(placed) / total if total > 0 else 0

    print(f"  Stages:       {len(PIPELINE_STAGES)} executed")
    print(f"  Placed:       {len(placed)}/{total}")
    print(f"  Dropped:      {len(dropped)}")
    print(f"  Success Rate: {success_rate:.1%}")
    print(f"  Verification: {'PASS' if verification and verification.passed else 'FAIL'}")
    if verification:
        print(f"  Blocking:     {len(verification.blocking)}")
        print(f"  Warnings:     {len(verification.warning)}")
    print(f"  Report:       {len(report)} chars")
    print(f"  GLB:          {len(glb_bytes)} bytes")
    print(f"  Fallback:     {result.get('fallback_used', False)}")
    print(f"  Retries:      {result.get('reset_count', 0)}")

    if verification and verification.blocking:
        print()
        print("BLOCKING issues:")
        for b in verification.blocking:
            print(f"  - {b.object_type}: {b.detail}")

    all_ok = (verification and verification.passed
              and len(placed) > 0 and len(glb_bytes) > 100)
    print()
    if all_ok:
        print("E2E PASS")
    else:
        print("E2E FAIL")
        if not verification or not verification.passed:
            print("  -> verification failed")
        if len(placed) == 0:
            print("  -> no objects placed")
        if len(glb_bytes) <= 100:
            print("  -> GLB too small")


if __name__ == "__main__":
    main()
