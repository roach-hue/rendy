"""P0/P1 runtime verification."""
# -*- coding: utf-8 -*-
import json
import os
import sys
from pathlib import Path

os.environ["PYTHONIOENCODING"] = "utf-8"
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")
from shapely.geometry import box as shapely_box, Polygon
from shapely.affinity import rotate as shapely_rotate

from app.schemas.drawings import ParsedDrawings
from app.agents.agent2_back import run as run_agent2
from app.agents.agent3_placement import plan_placement
from app.modules.object_selection import select_eligible_objects
from app.modules.failure_handler import run_with_fallback


def load_cache():
    cache_file = Path(__file__).parent.parent / "cache" / "last_session.json"
    if not cache_file.exists():
        print("ERROR: 캐시 파일 없음")
        sys.exit(1)
    return json.loads(cache_file.read_text(encoding="utf-8", errors="replace"))


def reconstruct_bbox(obj: dict) -> Polygon:
    """배치 결과에서 bbox polygon 재구성."""
    cx, cy = obj["center_x_mm"], obj["center_y_mm"]
    w, d = obj["width_mm"], obj["depth_mm"]
    rot = obj.get("rotation_deg", 0)
    rect = shapely_box(cx - w/2, cy - d/2, cx + w/2, cy + d/2)
    if rot != 0:
        rect = shapely_rotate(rect, rot, origin=(cx, cy))
    return rect


def check_overlaps(placed: list[dict]) -> list[str]:
    """모든 배치 쌍의 겹침 확인."""
    violations = []
    for i in range(len(placed)):
        for j in range(i + 1, len(placed)):
            a = reconstruct_bbox(placed[i])
            b = reconstruct_bbox(placed[j])
            overlap = a.intersection(b).area
            if overlap > 0:
                violations.append(
                    f"  {placed[i]['object_type']} ↔ {placed[j]['object_type']}: "
                    f"overlap={overlap:.0f}mm²"
                )
    return violations


def main():
    print("=" * 60)
    print("P0/P1 런타임 검증")
    print("=" * 60)

    # 캐시 로드
    cache = load_cache()
    drawings = ParsedDrawings.model_validate(cache["drawings"])
    brand_data = cache.get("brand_data", {})
    scale = cache.get("scale_mm_per_px", 10.0)

    # Agent 2 실행
    print("\n[1] Agent 2 실행...")
    sd = run_agent2(drawings=drawings, scale_mm_per_px=scale)
    slot_count = sum(1 for k, v in sd.items() if isinstance(v, dict) and "zone_label" in v and k != "floor")
    print(f"    slots 생성: {slot_count}개")

    # Zone 분포 확인
    zone_dist = {}
    for k, v in sd.items():
        if isinstance(v, dict) and "zone_label" in v and k != "floor":
            z = v["zone_label"]
            zone_dist[z] = zone_dist.get(z, 0) + 1
    print(f"    zone 분포: {zone_dist}")

    # Object Selection
    print("\n[2] Object Selection...")
    eligible = select_eligible_objects(sd, brand_data)
    print(f"    eligible: {len(eligible)}개")

    # Agent 3 기획
    print("\n[3] Agent 3 배치 기획...")
    placements = plan_placement(eligible, sd, brand_data)
    print(f"    placements: {len(placements)}개")

    # 배치 실행
    print("\n[4] 배치 엔진 + Fallback...")
    result = run_with_fallback(placements, eligible, sd, brand_data)

    placed = result["placed"]
    dropped = result["dropped"]
    total = len(placements)

    print(f"\n{'=' * 60}")
    print(f"결과 요약")
    print(f"{'=' * 60}")
    print(f"  총 기획: {total}개")
    print(f"  배치 성공: {len(placed)}개")
    print(f"  드랍: {len(dropped)}개")
    print(f"  드랍률: {len(dropped)/total*100:.1f}%" if total > 0 else "  드랍률: N/A")

    # 겹침 검사
    print(f"\n[겹침 검사]")
    overlaps = check_overlaps(placed)
    if overlaps:
        print(f"  ❌ 겹침 {len(overlaps)}건 발견:")
        for v in overlaps:
            print(v)
    else:
        print(f"  ✅ 겹침 0건 — 완전 해소")

    # 드랍 상세
    if dropped:
        print(f"\n[드랍 상세]")
        for d in dropped:
            print(f"  - {d.get('object_type', '?')}: {d.get('reason', '?')}")

    # fallback 사용 여부
    print(f"\n  fallback 사용: {result.get('fallback_used', False)}")

    print(f"\n{'=' * 60}")
    if not overlaps and len(dropped) == 0:
        print("🟢 P0/P1 검증 PASS — 겹침 0%, 드랍 0%")
    elif not overlaps:
        print(f"🟡 P0 PASS (겹침 0%), P1 부분 — 드랍 {len(dropped)}개 발생")
    else:
        print(f"🔴 P0 FAIL — 겹침 {len(overlaps)}건")


if __name__ == "__main__":
    main()
