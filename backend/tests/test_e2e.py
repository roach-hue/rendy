"""End-to-End pipeline test: cache load -> agent2 -> agent3 -> placement -> verification -> report -> glb."""
import json
import os
import sys
import base64
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

from app.schemas.drawings import ParsedDrawings
from app.agents.agent2_back import run as run_agent2
from app.agents.agent3_placement import plan_placement
from app.modules.object_selection import select_eligible_objects
from app.modules.failure_handler import run_with_fallback
from app.modules.verification import verify_placement
from app.modules.report_generator import generate_report
from app.modules.glb_exporter import export_glb


def main():
    print("=" * 60)
    print("E2E Pipeline Test")
    print("=" * 60)

    # 1. Cache load
    cache_file = Path(__file__).parent.parent / "cache" / "last_session.json"
    cache = json.loads(cache_file.read_text(encoding="utf-8", errors="replace"))
    drawings = ParsedDrawings.model_validate(cache["drawings"])
    brand_data = cache.get("brand_data", {})
    scale = cache.get("scale_mm_per_px", 10.0)
    print("[1] Cache loaded")

    # 2. Agent 2
    sd = run_agent2(drawings=drawings, scale_mm_per_px=scale)
    slot_count = sum(1 for k, v in sd.items() if isinstance(v, dict) and "zone_label" in v and k != "floor")
    print(f"[2] Agent 2: {slot_count} slots")

    # 3. Object Selection
    eligible = select_eligible_objects(sd, brand_data)
    print(f"[3] Selection: {len(eligible)} eligible")

    # 4. Agent 3
    placements = plan_placement(eligible, sd, brand_data)
    print(f"[4] Agent 3: {len(placements)} placements (max_slots={slot_count})")

    # 5. Placement Engine + Fallback
    result = run_with_fallback(placements, eligible, sd, brand_data)
    placed = result["placed"]
    dropped = result["dropped"]
    print(f"[5] Engine: {len(placed)} placed, {len(dropped)} dropped")

    # 6. Verification
    verification = verify_placement(placed, sd)
    print(f"[6] Verification: {'PASS' if verification.passed else 'FAIL'} "
          f"({len(verification.blocking)} blocking, {len(verification.warning)} warning)")

    # 7. Report
    report = generate_report(placed, dropped, verification.model_dump(), sd, brand_data, result["fallback_used"])
    print(f"[7] Report: {len(report)} chars, {report.count(chr(10))} lines")

    # 8. GLB
    glb_bytes = export_glb(placed, sd)
    glb_b64 = base64.b64encode(glb_bytes).decode()
    print(f"[8] GLB: {len(glb_bytes)} bytes ({len(glb_b64)} base64 chars)")

    # Summary
    print()
    print("=" * 60)
    print("E2E RESULT")
    print("=" * 60)
    print(f"  Placed:       {len(placed)}/{len(placements)}")
    print(f"  Dropped:      {len(dropped)}")
    print(f"  Verification: {'PASS' if verification.passed else 'FAIL'}")
    print(f"  Blocking:     {len(verification.blocking)}")
    print(f"  Warnings:     {len(verification.warning)}")
    print(f"  Report:       {len(report)} chars")
    print(f"  GLB:          {len(glb_bytes)} bytes")
    print(f"  Fallback:     {result['fallback_used']}")

    if verification.blocking:
        print()
        print("BLOCKING issues:")
        for b in verification.blocking:
            print(f"  - {b.object_type}: {b.detail}")

    all_ok = verification.passed and len(placed) > 0 and len(glb_bytes) > 100
    print()
    if all_ok:
        print("E2E PASS")
    else:
        print("E2E FAIL")
        if not verification.passed:
            print("  -> verification failed")
        if len(placed) == 0:
            print("  -> no objects placed")
        if len(glb_bytes) <= 100:
            print("  -> GLB too small")

    # JSON 응답 스키마 출력
    from app.schemas.verification import SummaryReport
    summary = SummaryReport(
        total_area_sqm=float(sd.get("floor", {}).get("usable_area_sqm", 0)),
        zone_distribution={p.get("zone_label", "?"): 0 for p in placed},
        placed_count=len(placed),
        dropped_count=len(dropped),
        success_rate=round(len(placed) / max(len(placed) + len(dropped), 1), 3),
        fallback_used=result["fallback_used"],
        slot_count=sum(1 for k, v in sd.items() if isinstance(v, dict) and "zone_label" in v and k != "floor"),
        verification_passed=verification.passed,
    )
    # zone_distribution 정확히 계산
    zd: dict[str, int] = {}
    for p in placed:
        z = p.get("zone_label", "unknown")
        zd[z] = zd.get(z, 0) + 1
    summary.zone_distribution = zd

    import json as _json
    response_schema = {
        "placed": f"[...{len(placed)} objects]",
        "dropped": f"[...{len(dropped)} objects]",
        "verification": verification.model_dump(),
        "report": f"(string, {len(report)} chars)",
        "glb_base64": f"(string, {len(glb_b64)} chars)",
        "log": f"[...{len(result['log'])} entries]",
        "summary": summary.model_dump(),
    }
    print()
    print("=" * 60)
    print("/api/placement JSON Response Schema:")
    print("=" * 60)
    print(_json.dumps(response_schema, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
