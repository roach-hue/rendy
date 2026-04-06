"""
DXF 파서 통합 테스트 — 6대 요구사항 + 3대 안전장치 검증.

실제 DXF 파일 없이 ezdxf로 인메모리 DXF를 생성하여 테스트.
곡선벽(ARC), 경사벽(LINE), TEXT 앵커링, 설비 심볼 전부 포함.
"""
import sys
import math
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import ezdxf

from app.parsers.dxf_parser import (
    DXFParser,
    _tessellate_arc,
    _tessellate_circle,
    _bulge_to_arc_points,
    _compute_origin_offset,
    _snap_endpoints,
    _build_outer_polygon,
    _collect_all_segments,
    _polygon_area,
    SNAP_TOLERANCE_MM,
    CHORD_TOLERANCE_MM,
)


def _create_test_dxf() -> bytes:
    """
    RENDEZ-VOUS POP-UP STORE 도면을 모사하는 테스트 DXF 생성.

    12000x12000mm 비정형 공간:
    - 하단: 직선 벽 12000mm
    - 좌측: 직선 벽 12000mm
    - 상단: 직선 8000mm + 45° 경사 5000mm
    - 우측: R=3000mm 곡선벽
    - STAFF ONLY 2개 구역 (좌측)
    - ENTRANCE 하단 중앙
    - 설비 심볼 3종
    """
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()

    # ── 외벽 (LWPOLYLINE + ARC) ─────────────────────────────────────────
    # 원점을 (1000, 2000)으로 오프셋 — 정규화 테스트용
    ox, oy = 1000, 2000

    # 하단 벽 (직선)
    msp.add_line((ox, oy), (ox + 12000, oy))
    # 좌측 벽 (직선)
    msp.add_line((ox, oy), (ox, oy + 12000))
    # 상단 좌측 (직선 8000mm)
    msp.add_line((ox, oy + 12000), (ox + 8000, oy + 12000))
    # 45° 경사벽 (8000,12000) → (12000,8000) 근사
    msp.add_line((ox + 8000, oy + 12000), (ox + 12000, oy + 8000))
    # R=3000mm 곡선벽 (우측, (12000,8000)→(12000,0) 구간 일부)
    # ARC: center=(12000+3000, 4000) = 우측 바깥, 반지름 맞춤
    # 단순화: (12000,8000)→(12000,0) 직선으로 잇고 ARC 별도 테스트
    msp.add_line((ox + 12000, oy + 8000), (ox + 12000, oy))

    # 독립 ARC 테스트 (도면 내부의 곡선 디스플레이 테이블 등)
    msp.add_arc(
        center=(ox + 8000, oy + 5000),
        radius=3000,
        start_angle=180,
        end_angle=270,
    )

    # CIRCLE (기둥)
    msp.add_circle(center=(ox + 6000, oy + 6000), radius=300)

    # ── 내부 벽 (STAFF ONLY 구획) ────────────────────────────────────────
    wall_layer = "A-WALL-INTERIOR"
    # 상단 STAFF ONLY 구획 (0~2000, 8000~12000)
    msp.add_line(
        (ox, oy + 8000), (ox + 2000, oy + 8000),
        dxfattribs={"layer": wall_layer},
    )
    msp.add_line(
        (ox + 2000, oy + 8000), (ox + 2000, oy + 12000),
        dxfattribs={"layer": wall_layer},
    )
    # 하단 STAFF ONLY 구획 (0~2000, 0~4000)
    msp.add_line(
        (ox, oy + 4000), (ox + 2000, oy + 4000),
        dxfattribs={"layer": wall_layer},
    )
    msp.add_line(
        (ox + 2000, oy), (ox + 2000, oy + 4000),
        dxfattribs={"layer": wall_layer},
    )

    # ── TEXT 앵커링 ──────────────────────────────────────────────────────
    msp.add_text(
        "ENTRANCE",
        dxfattribs={"insert": (ox + 6000, oy - 200), "height": 200},
    )
    msp.add_text(
        "STAFF ONLY",
        dxfattribs={"insert": (ox + 800, oy + 10000), "height": 150},
    )
    msp.add_text(
        "STAFF ONLY",
        dxfattribs={"insert": (ox + 800, oy + 2000), "height": 150},
    )

    # ── 설비 심볼 (INSERT 블록) ──────────────────────────────────────────
    # 스프링클러 블록
    sp_block = doc.blocks.new(name="SPK-01")
    sp_block.add_circle(center=(0, 0), radius=50)
    msp.add_blockref("SPK-01", insert=(ox + 4000, oy + 6000))
    msp.add_blockref("SPK-01", insert=(ox + 8000, oy + 6000))

    # 소화전 블록
    fh_block = doc.blocks.new(name="FIRE_HYDRANT")
    fh_block.add_circle(center=(0, 0), radius=100)
    msp.add_blockref("FIRE_HYDRANT", insert=(ox + 200, oy + 200))

    # 분전반 블록
    ep_block = doc.blocks.new(name="EPS-PANEL")
    ep_block.add_circle(center=(0, 0), radius=80)
    msp.add_blockref("EPS-PANEL", insert=(ox + 100, oy + 6000))

    # 문 블록 (입구)
    door_block = doc.blocks.new(name="DOOR-MAIN")
    door_block.add_line((0, 0), (0, 1000))
    msp.add_blockref(
        "DOOR-MAIN",
        insert=(ox + 5500, oy),
        dxfattribs={"xscale": 3000},  # 입구 폭 3000mm
    )

    # 바이트로 변환 (ezdxf write → StringIO → encode)
    import io as _io
    stream = _io.StringIO()
    doc.write(stream)
    return stream.getvalue().encode("utf-8")


import asyncio

print("=" * 60)
print("DXF Parser Integration Test")
print("=" * 60)


# ── Test 1: 전체 파이프라인 실행 ──────────────────────────────────────────

print("\n[Test 1] Full pipeline execution")
dxf_bytes = _create_test_dxf()
parser = DXFParser(floor_bytes=dxf_bytes)
result = asyncio.run(parser.parse())

fp = result.floor_plan
print(f"  floor_polygon: {len(fp.floor_polygon_px)} points")
print(f"  scale_mm_per_px: {fp.scale_mm_per_px}")
print(f"  scale_confirmed: {fp.scale_confirmed}")
print(f"  detected_dims: {fp.detected_width_mm} x {fp.detected_height_mm}")
print(f"  entrances: {len(fp.entrances)}")
print(f"  sprinklers: {len(fp.sprinklers)}")
print(f"  fire_hydrant: {len(fp.fire_hydrant)}")
print(f"  electrical_panel: {len(fp.electrical_panel)}")
print(f"  inner_walls: {len(fp.inner_walls)}")
print(f"  inaccessible_rooms: {len(fp.inaccessible_rooms)}")

assert fp.scale_mm_per_px == 1.0, "DXF scale must be 1.0"
assert fp.scale_confirmed is True, "DXF scale must be confirmed"
print("  PASS")


# ── Test 2: 안전장치 1 — 좌표 정규화 검증 ────────────────────────────────

print("\n[Test 2] Safety 1: Coordinate normalization")
all_x = [p[0] for p in fp.floor_polygon_px]
all_y = [p[1] for p in fp.floor_polygon_px]
min_x = min(all_x)
min_y = min(all_y)
print(f"  polygon min: ({min_x}, {min_y})")
# 원점이 (0,0) 근처여야 함 (스냅 톨러런스 이내)
# DXF 원점 오프셋이 (1000, 2000)이었으므로 정규화 후 ~(0,0) 부근
# ARC/다른 엔티티가 음수 좌표를 만들 수 있으므로 min이 0 근처이면 OK
assert min_x >= -500, f"min_x too negative: {min_x}"
assert min_y >= -500, f"min_y too negative: {min_y}"
print("  PASS")


# ── Test 3: 안전장치 2 — 스냅 톨러런스 ──────────────────────────────────

print("\n[Test 3] Safety 2: Snap tolerance")
# 5mm 이내 갭이 있는 선분 → 병합 후 polygonize 성공
gap_segs = [
    [(0, 0), (1000, 0)],
    [(1000.003, 0.002), (1000, 1000)],  # 3mm 갭
    [(1000, 1000.004), (0, 1000)],      # 4mm 갭
    [(0, 999.997), (0, 0)],             # 3mm 갭
]
snapped = _snap_endpoints(gap_segs, 5.0)
polygon = _build_outer_polygon(snapped)
assert polygon is not None, "Snap should enable polygonize"
area = _polygon_area(polygon)
print(f"  gapped segments → polygon area={area:.0f}mm² ({len(polygon)}pts)")
assert area > 900000, f"area too small: {area}"
print("  PASS")


# ── Test 4: ARC tessellation 정밀도 ──────────────────────────────────────

print("\n[Test 4] ARC tessellation precision")
# R=3000mm, 90° → arc_length = 3000 * π/2 ≈ 4712mm
# N = max(8, 4712/50) = 94 segments → 95 points
pts = _tessellate_arc(0, 0, 3000, 0, 90)
print(f"  R=3000, 90deg: {len(pts)} points")
assert len(pts) > 50, "insufficient tessellation"

# 모든 점이 반지름 ± 1mm 이내
for px, py in pts:
    r = math.hypot(px, py)
    assert abs(r - 3000) < 1, f"point ({px},{py}) off circle: r={r}"
print("  all points on circle (±1mm)")

# R=500mm, 360° → full circle
circle = _tessellate_circle(1000, 1000, 500)
print(f"  R=500, full circle: {len(circle)} points")
assert len(circle) >= 30
print("  PASS")


# ── Test 5: TEXT 앵커링 — 입구 감지 ──────────────────────────────────────

print("\n[Test 5] TEXT anchoring — entrance detection")
assert len(fp.entrances) >= 1, "ENTRANCE text should be detected"
main_entrances = [e for e in fp.entrances if e.is_main and e.type == "MAIN_DOOR"]
print(f"  main entrances: {len(main_entrances)}")
assert len(main_entrances) >= 1
# 입구 좌표가 정규화 후 합리적 범위
for e in main_entrances:
    print(f"    ({e.x_px}, {e.y_px}) type={e.type}")
    assert -500 <= e.x_px <= 15000
    assert -500 <= e.y_px <= 15000
print("  PASS")


# ── Test 6: TEXT 앵커링 — inaccessible_rooms ─────────────────────────────

print("\n[Test 6] TEXT anchoring — inaccessible rooms")
assert len(fp.inaccessible_rooms) >= 2, \
    f"2 STAFF ONLY texts → ≥2 inaccessible, got {len(fp.inaccessible_rooms)}"
for i, room in enumerate(fp.inaccessible_rooms):
    print(f"  room {i}: {len(room.polygon_px)} pts, confidence={room.confidence}")
    # 폐합 polygon 검증: 최소 4점
    assert len(room.polygon_px) >= 4
print("  PASS")


# ── Test 7: 안전장치 4 — 폴백 사각형 검증 ────────────────────────────────

print("\n[Test 7] Safety 4: Fallback rectangle")
# 폐합선 없는 구역은 confidence="medium" + 2000x2000
medium_rooms = [r for r in fp.inaccessible_rooms if r.confidence == "medium"]
if medium_rooms:
    for r in medium_rooms:
        xs = [p[0] for p in r.polygon_px]
        ys = [p[1] for p in r.polygon_px]
        w = max(xs) - min(xs)
        h = max(ys) - min(ys)
        print(f"  fallback: {w:.0f}x{h:.0f}mm")
        assert abs(w - 2000) < 1, f"fallback width wrong: {w}"
        assert abs(h - 2000) < 1, f"fallback height wrong: {h}"
    print("  PASS")
else:
    # 폐합선이 모두 찾아진 경우 → 안전장치 4가 발동하지 않음 (정상)
    print("  (all rooms found enclosing polygon — fallback not triggered)")
    print("  PASS (fallback not needed)")


# ── Test 8: 설비 심볼 추출 ───────────────────────────────────────────────

print("\n[Test 8] Equipment symbol extraction")
assert len(fp.sprinklers) == 2, f"expected 2 sprinklers, got {len(fp.sprinklers)}"
assert len(fp.fire_hydrant) == 1, f"expected 1 hydrant, got {len(fp.fire_hydrant)}"
assert len(fp.electrical_panel) == 1, f"expected 1 panel, got {len(fp.electrical_panel)}"
for sp in fp.sprinklers:
    print(f"  sprinkler: ({sp.x_px}, {sp.y_px})")
print(f"  hydrant: ({fp.fire_hydrant[0].x_px}, {fp.fire_hydrant[0].y_px})")
print(f"  panel: ({fp.electrical_panel[0].x_px}, {fp.electrical_panel[0].y_px})")
print("  PASS")


# ── Test 9: 출력 스키마 무결성 ───────────────────────────────────────────

print("\n[Test 9] Schema consistency")
# ParsedDrawings 직렬화 성공 여부
json_str = result.model_dump_json()
assert len(json_str) > 100
print(f"  JSON serialization: {len(json_str)} chars")
# 필수 필드 존재
d = result.model_dump()
assert "floor_plan" in d
assert "floor_polygon_px" in d["floor_plan"]
assert d["floor_plan"]["scale_mm_per_px"] == 1.0
assert d["floor_plan"]["scale_confirmed"] is True
print("  PASS")


# ── Test 10: LWPOLYLINE bulge (원호 세그먼트) ────────────────────────────

print("\n[Test 10] LWPOLYLINE bulge tessellation")
arc_pts = _bulge_to_arc_points(0, 0, 1000, 0, 1.0)  # bulge=1 → 반원
print(f"  bulge=1.0 (semicircle): {len(arc_pts)} points")
assert len(arc_pts) >= 8

# 최고점이 현(chord) 위에 있어야 함 (반원이므로 y > 0)
max_y = max(p[1] for p in arc_pts)
print(f"  max_y={max_y:.1f} (should be ~500)")
assert max_y > 400, f"bulge arc too flat: max_y={max_y}"
print("  PASS")


print()
print("=" * 60)
print("DXF Parser ALL TESTS PASS")
print("=" * 60)
