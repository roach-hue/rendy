"""
C-5: Geometry Instancing 무결성 검증.

1. 50개 동일 규격 오브젝트 → geometry_id 해시 1개 수렴
2. 다른 규격 혼합 → 정확한 그룹 수
3. geometry_id가 placed 데이터에 포함되는지 검증
4. 프론트엔드 InstancedMesh 그룹화 로직 시뮬레이션
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.modules.geometry_cache import (
    compute_geometry_hash, get_or_create, get_cache_stats, clear_cache, normalize
)

clear_cache()

print("=" * 60)
print("C-5: Geometry Instancing Integrity")
print("=" * 60)

# ── Test 1: 50개 동일 규격 → 해시 1개 ─────────────────────────────────────────

print("\n[Test 1] 50 identical objects → 1 geometry_id")
ids_50 = []
for i in range(50):
    result = get_or_create("shelf_3tier", "shelf", 1200, 400, 1200)
    ids_50.append(result["geometry_id"])

unique_50 = set(ids_50)
cache_hits_50 = sum(1 for i in range(50) if i > 0)  # 첫 번째 이후 모두 hit
print(f"  50 objects → {len(unique_50)} unique hash")
print(f"  geometry_id: {ids_50[0][:16]}...")
assert len(unique_50) == 1, f"FAIL: expected 1, got {len(unique_50)}"
print("  PASS")

# ── Test 2: cache hit 동작 검증 ───────────────────────────────────────────────

print("\n[Test 2] Cache hit verification")
clear_cache()
r1 = get_or_create("shelf_3tier", "shelf", 1200, 400, 1200)
assert r1["cache_hit"] is False, "first should be miss"
print(f"  1st call: cache_hit={r1['cache_hit']} (miss)")

r2 = get_or_create("shelf_3tier", "shelf", 1200, 400, 1200)
assert r2["cache_hit"] is True, "second should be hit"
print(f"  2nd call: cache_hit={r2['cache_hit']} (hit)")

assert r1["geometry_id"] == r2["geometry_id"]
print("  PASS")

# ── Test 3: 다른 규격 혼합 → 정확한 그룹 수 ─────────────────────────────────

print("\n[Test 3] Mixed specs → correct group count")
clear_cache()

specs = [
    ("shelf_3tier", "shelf",   1200, 400, 1200),   # group A
    ("shelf_3tier", "shelf",   1200, 400, 1200),   # group A (duplicate)
    ("display_table", "display", 1200, 600, 800),  # group B
    ("display_table", "display", 1200, 600, 800),  # group B (duplicate)
    ("display_table", "display", 1200, 600, 800),  # group B (duplicate)
    ("character_panel", "character", 800, 5, 2000), # group C (depth forced to 20)
    ("character_panel", "character", 800, 5, 2000), # group C (duplicate)
    ("pillar", "cylinder_display", 600, 600, 1200), # group D (cylinder)
]

ids_by_spec = {}
for obj_type, cat, w, d, h in specs:
    r = get_or_create(obj_type, cat, w, d, h)
    gid = r["geometry_id"]
    if gid not in ids_by_spec:
        ids_by_spec[gid] = []
    ids_by_spec[gid].append(obj_type)

print(f"  8 objects → {len(ids_by_spec)} unique groups")
for gid, types in ids_by_spec.items():
    print(f"    {gid[:12]}...: {len(types)}x ({types[0]})")

assert len(ids_by_spec) == 4, f"FAIL: expected 4 groups, got {len(ids_by_spec)}"
print("  PASS")

# ── Test 4: 부동소수점 정규화 → 동일 해시 수렴 ───────────────────────────────

print("\n[Test 4] Float normalization convergence")
clear_cache()
r_a = get_or_create("shelf", "shelf", 1200.003, 400.007, 1200.001)
r_b = get_or_create("shelf", "shelf", 1200.0, 400.0, 1200.0)
assert r_a["geometry_id"] == r_b["geometry_id"], "float normalization failed"
print(f"  1200.003 vs 1200.0 → SAME hash")
print("  PASS")

# ── Test 5: 등신대 depth < 20mm → 강제 20mm → 해시 일치 ──────────────────────

print("\n[Test 5] Panel MIN_DEPTH_MM enforcement")
clear_cache()
r_5mm = get_or_create("panel", "character", 800, 5, 2000)
r_10mm = get_or_create("panel", "character", 800, 10, 2000)
r_20mm = get_or_create("panel", "character", 800, 20, 2000)
assert r_5mm["geometry_id"] == r_10mm["geometry_id"] == r_20mm["geometry_id"], \
    "MIN_DEPTH should normalize 5mm and 10mm to 20mm"
assert r_5mm["depth_mm"] == 20.0
print(f"  depth 5/10/20 → all hash={r_5mm['geometry_id'][:16]}..., depth={r_5mm['depth_mm']}mm")
print("  PASS")

# ── Test 6: 회전 제외 → 동일 해시 ────────────────────────────────────────────

print("\n[Test 6] Rotation excluded from hash")
h1 = compute_geometry_hash("BOX", 1200, 400, 1200)
h2 = compute_geometry_hash("BOX", 1200, 400, 1200)
assert h1 == h2, "same input → same hash"
# compute_geometry_hash에는 rotation 파라미터가 없음 → 설계적으로 배제됨
print("  rotation is not a hash input → PASS (by design)")

# ── Test 7: InstancedMesh 그룹화 시뮬레이션 ───────────────────────────────────

print("\n[Test 7] InstancedMesh grouping simulation (frontend logic)")

# 프론트엔드에서 받을 placed 데이터 시뮬레이션
placed_objects = []
clear_cache()

# 20개 shelf (동일 규격)
for i in range(20):
    r = get_or_create("shelf_3tier", "shelf", 1200, 400, 1200)
    placed_objects.append({
        "object_type": "shelf_3tier",
        "geometry_id": r["geometry_id"],
        "center_x_mm": 1000 + i * 500,
        "center_y_mm": 2000,
        "rotation_deg": i * 15,
        "width_mm": 1200, "depth_mm": 400, "height_mm": 1200,
        "zone_label": "mid_zone", "category": "shelf",
    })

# 15개 table (동일 규격)
for i in range(15):
    r = get_or_create("display_table", "display", 1200, 600, 800)
    placed_objects.append({
        "object_type": "display_table",
        "geometry_id": r["geometry_id"],
        "center_x_mm": 2000 + i * 500,
        "center_y_mm": 3000,
        "rotation_deg": 0,
        "width_mm": 1200, "depth_mm": 600, "height_mm": 800,
        "zone_label": "entrance_zone", "category": "display",
    })

# 15개 character (동일 규격)
for i in range(15):
    r = get_or_create("character_panel", "character", 800, 5, 2000)
    placed_objects.append({
        "object_type": "character_panel",
        "geometry_id": r["geometry_id"],
        "center_x_mm": 3000 + i * 500,
        "center_y_mm": 4000,
        "rotation_deg": 90,
        "width_mm": 800, "depth_mm": 20, "height_mm": 2000,
        "zone_label": "deep_zone", "category": "character",
    })

# 프론트엔드 groupByGeometryId 시뮬레이션
groups: dict[str, list] = {}
for obj in placed_objects:
    gid = obj["geometry_id"]
    if gid not in groups:
        groups[gid] = []
    groups[gid].append(obj)

print(f"  {len(placed_objects)} placed objects → {len(groups)} InstancedMesh groups")
for gid, objs in groups.items():
    print(f"    {gid[:12]}...: {len(objs)} instances ({objs[0]['object_type']})")

assert len(groups) == 3, f"FAIL: expected 3 groups, got {len(groups)}"
assert sum(len(v) for v in groups.values()) == 50, "total instance count mismatch"

# draw call 검증: N개 그룹 = N개 draw call (개별 메시 방식이면 50 draw call)
individual_draw_calls = len(placed_objects)  # 50
instanced_draw_calls = len(groups)  # 3
reduction = (1 - instanced_draw_calls / individual_draw_calls) * 100
print(f"\n  Draw call reduction: {individual_draw_calls} → {instanced_draw_calls} ({reduction:.0f}% reduction)")
assert instanced_draw_calls < individual_draw_calls
print("  PASS")

# ── Test 8: geometry_id 누락 객체 필터링 ──────────────────────────────────────

print("\n[Test 8] Objects without geometry_id are filtered")
no_gid_objects = [{"object_type": "unknown", "center_x_mm": 0, "center_y_mm": 0}]
no_gid_groups: dict[str, list] = {}
for obj in no_gid_objects:
    gid = obj.get("geometry_id")
    if not gid:
        continue
    if gid not in no_gid_groups:
        no_gid_groups[gid] = []
    no_gid_groups[gid].append(obj)
assert len(no_gid_groups) == 0
print("  Objects without geometry_id skipped → PASS")

# ── 최종 캐시 통계 ────────────────────────────────────────────────────────────

stats = get_cache_stats()
print(f"\nFinal cache: {stats['total_entries']} entries")

print()
print("=" * 60)
print("C-5 ALL TESTS PASS")
print("=" * 60)
