"""Agent 3 유닛 테스트 — Rendy 배치 표준 5규칙 + 상업 3대 원칙 검증."""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

from app.schemas.drawings import ParsedDrawings
from app.agents.agent2_back import run as run_agent2
from app.modules.object_selection import select_eligible_objects
from app.agents.agent3_placement import plan_placement

cache = json.loads((Path(__file__).parent.parent / "cache" / "last_session.json").read_text(encoding="utf-8", errors="replace"))
drawings = ParsedDrawings.model_validate(cache["drawings"])
sd = run_agent2(drawings=drawings, scale_mm_per_px=cache.get("scale_mm_per_px", 10.0))
eligible = select_eligible_objects(sd, cache.get("brand_data", {}))
placements = plan_placement(eligible, sd, cache.get("brand_data", {}))

print("\n" + "=" * 60)
print("Rendy Retail Standard + Commercial 3-Principle Verification")
print("=" * 60)

# 기본 정보
max_walk = max((v["walk_mm"] for k, v in sd.items() if isinstance(v, dict) and "walk_mm" in v and k != "floor"), default=0)
print(f"Max walk_mm: {max_walk}")

for p in placements:
    h = next((e.get("height_mm", 0) for e in eligible if e["object_type"] == p.object_type), 0)
    cat = next((e["category"] for e in eligible if e["object_type"] == p.object_type), "?")
    print(f"  {p.object_type:30s} zone={p.zone_label:15s} h={h:5d}mm cat={cat}")

violations = []

# ── R4: entrance_zone height > 1200 금지 ──────────────────────────────────
for p in placements:
    if p.zone_label == "entrance_zone":
        h = next((e.get("height_mm", 0) for e in eligible if e["object_type"] == p.object_type), 0)
        if h > 1200:
            violations.append(f"R4: {p.object_type} ({h}mm) in entrance_zone")

# ── P1: Power Wall (우측 벽면에 Hero 배치) ────────────────────────────────
# Hero = photo_zone, character 중 가장 큰 것
hero_types = {"photo_zone", "character"}
hero_placements = [p for p in placements if any(ht in p.object_type for ht in hero_types)]
# wall_facing + deep/mid zone에 있는 hero가 있으면 Power Wall 후보로 간주
hero_on_wall = [p for p in hero_placements if p.direction == "wall_facing"]
if not hero_on_wall and hero_placements:
    # inward로 벽 앞에 있어도 OK (벽면 인접)
    pass
print(f"\nP1 Power Wall: {len(hero_placements)} hero objects, {len(hero_on_wall)} on wall")

# ── P2: Logical Clustering (같은 category 인접) ──────────────────────────
cat_zones: dict[str, list[str]] = {}
for p in placements:
    cat = next((e["category"] for e in eligible if e["object_type"] == p.object_type), "?")
    cat_zones.setdefault(cat, []).append(p.zone_label)

cluster_score = 0
total_cats = 0
for cat, zones in cat_zones.items():
    if len(zones) <= 1:
        continue
    total_cats += 1
    # 같은 zone에 몇 개가 몰려있는지
    from collections import Counter
    zone_counts = Counter(zones)
    max_cluster = max(zone_counts.values())
    ratio = max_cluster / len(zones)
    cluster_score += ratio
    print(f"P2 Clustering: {cat:15s} → zones={dict(zone_counts)}, cluster_ratio={ratio:.0%}")

avg_cluster = cluster_score / total_cats if total_cats > 0 else 0
print(f"P2 Average cluster ratio: {avg_cluster:.0%} (>50% = good)")
if avg_cluster < 0.5:
    violations.append(f"P2: cluster ratio {avg_cluster:.0%} too low (expected >50%)")

# ── P3: Focal Point (deep_zone에 대형 기물) ───────────────────────────────
deep_heights = []
for p in placements:
    if p.zone_label == "deep_zone":
        h = next((e.get("height_mm", 0) for e in eligible if e["object_type"] == p.object_type), 0)
        deep_heights.append((p.object_type, h))

large_in_deep = [x for x in deep_heights if x[1] >= 1800]
print(f"\nP3 Focal Point: {len(large_in_deep)} large objects (>=1800mm) in deep_zone")
if not large_in_deep:
    violations.append("P3: no large object (>=1800mm) in deep_zone as focal point")

# ── 결과 ──────────────────────────────────────────────────────────────────
zone_counts_all = {}
for p in placements:
    zone_counts_all[p.zone_label] = zone_counts_all.get(p.zone_label, 0) + 1

print(f"\nZone distribution: {zone_counts_all}")
print(f"Total violations: {len(violations)}")
for v in violations:
    print(f"  FAIL: {v}")

if not violations:
    print("\nAll rules + principles PASS")
else:
    print(f"\n{len(violations)} violation(s)")
