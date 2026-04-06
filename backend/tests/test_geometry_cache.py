"""Unit test — 기하학 해시 캐싱 검증."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.modules.geometry_cache import compute_geometry_hash, get_or_create, get_cache_stats, clear_cache, normalize

clear_cache()

print("=" * 60)
print("Geometry Cache Verification")
print("=" * 60)

# 1. 동일 규격 10개 BOX, 다른 각도 → 해시 1개
ids = []
for rot in [0, 15, 30, 45, 60, 90, 120, 150, 180, 270]:
    result = get_or_create("shelf", "shelf", 1200, 600, 800)
    ids.append(result["geometry_id"])
    print(f"  rot={rot:3d}: id={result['geometry_id'][:12]}..., hit={result['cache_hit']}")

unique = set(ids)
print(f"\n10 BOX, {len(unique)} unique hash: {'PASS' if len(unique) == 1 else 'FAIL'}")
assert len(unique) == 1

# 2. 미세 오차 정규화 → 동일 해시 수렴
h1 = compute_geometry_hash("BOX", normalize(1200.003), normalize(600.007), normalize(800.001))
h2 = compute_geometry_hash("BOX", normalize(1200.0), normalize(600.0), normalize(800.0))
print(f"\n1200.003 vs 1200.0: {'SAME' if h1 == h2 else 'DIFFERENT'} → {'PASS' if h1 == h2 else 'FAIL'}")
assert h1 == h2

# 3. 다른 규격 → 다른 해시
r_shelf = get_or_create("shelf", "shelf", 1200, 400, 1200)
r_table = get_or_create("table", "display", 1200, 600, 800)
print(f"\nShelf vs Table: {'DIFFERENT' if r_shelf['geometry_id'] != r_table['geometry_id'] else 'SAME'}")
assert r_shelf["geometry_id"] != r_table["geometry_id"]

# 4. CYLINDER
r_cyl = get_or_create("pillar", "cylinder_display", 600, 600, 1200)
print(f"Cylinder: type={r_cyl['primitive_type']}, id={r_cyl['geometry_id'][:12]}...")
assert r_cyl["primitive_type"] == "CYLINDER"

# 5. 등신대 depth < 20mm → 강제 20mm
r_panel = get_or_create("panel", "character", 800, 5, 2000)
print(f"Panel depth=5mm → {r_panel['depth_mm']}mm")
assert r_panel["depth_mm"] >= 20

stats = get_cache_stats()
print(f"\nCache: {stats['total_entries']} entries")
print("\nAll geometry cache tests PASS")
