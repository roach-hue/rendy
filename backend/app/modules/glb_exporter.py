"""
P0-7b — .glb 출력 (Whitebox 3D)

배치 결과 → trimesh Box 메시 → 단일 .glb 파일 내보내기.
Whitebox = 텍스처 없는 단색 박스. 디자이너가 SketchUp 등에서 실제 모델로 교체.

좌표계: mm 단위, Y-up (Three.js 기본).
  - space_data 좌표 (X, Y) → glb (X, Z), height → Y
"""
import math
from pathlib import Path

import trimesh
from trimesh.visual.material import PBRMaterial


# zone별 색상 (RGBA 0~255)
ZONE_COLORS = {
    "entrance_zone": [76, 175, 80, 255],
    "mid_zone":      [255, 152, 0, 255],
    "deep_zone":     [33, 150, 243, 255],
    "unknown":       [158, 158, 158, 255],
}

FLOOR_COLOR = [240, 240, 240, 255]
WALL_COLOR  = [180, 180, 180, 255]


def _apply_color(mesh: trimesh.Trimesh, rgba: list[int]) -> None:
    """
    trimesh 메시에 glTF 표준 PBR material 적용.
    PBRMaterial → pbrMetallicRoughness.baseColorFactor (Three.js 완전 호환).
    """
    r, g, b, a = [c / 255.0 for c in rgba]
    mat = PBRMaterial(
        baseColorFactor=[r, g, b, a],
        metallicFactor=0.0,
        roughnessFactor=0.6,
    )
    mesh.visual = trimesh.visual.TextureVisuals(material=mat)


def export_glb(
    placed: list[dict],
    space_data: dict,
    output_path: str | None = None,
) -> bytes:
    """
    배치 결과 → .glb 바이트 반환.
    output_path 지정 시 파일로도 저장.
    """
    scene = trimesh.Scene()

    # 바닥 평면 — Shapely polygon을 X반전하여 좌우 거울상 해소
    from shapely import affinity
    floor_poly_raw = space_data.get("floor", {}).get("polygon")
    floor_poly = affinity.scale(floor_poly_raw, xfact=-1, yfact=1, origin=(0, 0)) if floor_poly_raw else None
    if floor_poly:
        floor_mesh = _create_floor(floor_poly)
        scene.add_geometry(floor_mesh, node_name="floor")

    # 벽면 (높이 3000mm 기본)
    ceiling_h = _get_ceiling_height(space_data)
    if floor_poly:
        wall_meshes = _create_walls(floor_poly, ceiling_h)
        for i, wm in enumerate(wall_meshes):
            scene.add_geometry(wm, node_name=f"wall_{i}")

    # 배치된 오브젝트 (whitebox) — geometry_cache 경유
    from app.modules.geometry_cache import get_or_create
    for i, obj in enumerate(placed):
        # 캐시 등록 (해시 기반 중복 방지)
        geo = get_or_create(
            obj_type=obj["object_type"],
            category=obj.get("category", ""),
            width_mm=obj["width_mm"],
            depth_mm=obj["depth_mm"],
            height_mm=obj.get("height_mm", 1000),
        )
        obj["geometry_id"] = geo["geometry_id"]

        print(f"[GLBExporter] obj {i}: {obj['object_type']} "
              f"w={obj['width_mm']} d={obj['depth_mm']} h={obj.get('height_mm','?')} "
              f"gid={geo['geometry_id'][:8]}...")
        box_mesh = _create_object_mesh(obj, ceiling_h)
        scene.add_geometry(box_mesh, node_name=f"obj_{i}_{obj['object_type']}")

    # .glb 내보내기
    glb_bytes = scene.export(file_type="glb")

    if output_path:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "wb") as f:
            f.write(glb_bytes)
        print(f"[GLBExporter] saved to {output_path} ({len(glb_bytes)} bytes)")

    print(f"[GLBExporter] exported: {len(placed)} objects, {len(glb_bytes)} bytes")
    return glb_bytes


# ── 메시 생성 헬퍼 ──────────────────────────────────────────────────────────

def _create_floor(floor_poly) -> trimesh.Trimesh:
    """
    바닥 평면 메시 (Y=0, 두께 10mm).
    Shapely polygon → extrude로 비정형 평면도 지원.
    실패 시 bbox fallback.

    좌표 변환 순서:
    1. extrude_polygon → XY 평면 + Z 높이 10mm
    2. centroid를 원점으로 이동 (회전 시 스윙 방지)
    3. X축 -90° 회전 (Y→Z swap: XY평면 → XZ평면)
    4. centroid를 벽과 동일한 최종 좌표로 복원
       벽은 (cx, height/2, cy) 방식 — 바닥은 (cx, 0, cy)
    """
    minx, miny, maxx, maxy = floor_poly.bounds
    cx = (minx + maxx) / 2
    cy = (miny + maxy) / 2

    try:
        floor = trimesh.creation.extrude_polygon(floor_poly, height=10)

        # Y↔Z 축 swap: Shapely XY평면 → Three.js XZ평면 (Y-up)
        # X반전은 Shapely polygon 레벨에서 이미 적용됨 (export_glb)
        import numpy as np
        swap_yz = np.array([
            [1, 0, 0, 0],
            [0, 0, 1, 0],
            [0, 1, 0, 0],
            [0, 0, 0, 1],
        ], dtype=float)
        floor.apply_transform(swap_yz)
        floor.apply_translation([0, -5, 0])
        floor.fix_normals()

        _apply_color(floor, FLOOR_COLOR)
        print(f"[GLBExporter] floor: extrude_polygon ({len(floor.faces)} faces), "
              f"bounds={floor_poly.bounds}, center=({cx:.0f},{cy:.0f})")
        return floor
    except Exception as e:
        print(f"[GLBExporter] extrude_polygon failed ({e}), bbox fallback")
        w = maxx - minx
        d = maxy - miny
        floor = trimesh.creation.box(extents=[w, 10, d])
        floor.apply_translation([-cx, -5, cy])  # polygon이 이미 X반전됨 → cx도 반전 상태
        _apply_color(floor, FLOOR_COLOR)
        return floor


def _create_walls(floor_poly, height_mm: float) -> list[trimesh.Trimesh]:
    """외벽 메시 리스트. 각 변을 얇은 박스로 생성."""
    coords = list(floor_poly.exterior.coords)
    walls = []
    wall_thickness = 50  # 50mm 두께

    for i in range(len(coords) - 1):
        x1, y1 = coords[i]
        x2, y2 = coords[i + 1]
        length = math.hypot(x2 - x1, y2 - y1)
        if length < 10:
            continue

        # 벽 중심 — polygon이 이미 X반전됨
        cx = (x1 + x2) / 2
        cy = (y1 + y2) / 2
        angle = math.atan2(y2 - y1, x2 - x1)

        wall = trimesh.creation.box(
            extents=[length, height_mm, wall_thickness],
        )
        rot = trimesh.transformations.rotation_matrix(-angle, [0, 1, 0])
        wall.apply_transform(rot)
        wall.apply_translation([cx, height_mm / 2, cy])
        _apply_color(wall, WALL_COLOR)
        walls.append(wall)

    return walls


# 등신대/배너 등 Plane형 기물의 최소 두께 (mm) — geometry_cache에서 정의
from app.modules.geometry_cache import MIN_DEPTH_MM


def _create_object_mesh(obj: dict, ceiling_h: float) -> trimesh.Trimesh:
    """
    파라메트릭 화이트박스 메시 생성.

    Primitive 타입:
    - BOX: 사각형 기물 전반 (테이블, 선반, 카운터, 등신대/배너)
    - CYLINDER: 원형 매대/기둥 (category에 "cylinder"/"round"/"column" 포함 시)

    등신대/배너: depth < MIN_DEPTH_MM이면 MIN_DEPTH_MM으로 강제 (충돌 영역 확보).
    """
    w = obj["width_mm"]
    d = obj["depth_mm"]
    h = obj.get("height_mm", 1000)
    cx = obj["center_x_mm"]
    cy = obj["center_y_mm"]
    rot_deg = obj.get("rotation_deg", 0)
    category = obj.get("category", "")

    # 등신대/배너: 최소 두께 20mm 보장
    if d < MIN_DEPTH_MM:
        d = MIN_DEPTH_MM

    # Primitive 타입 결정
    is_cylinder = any(kw in category.lower() for kw in ("cylinder", "round", "column", "pillar"))

    if is_cylinder:
        # CYLINDER: diameter = max(w, d), height = h
        diameter = max(w, d)
        mesh = trimesh.creation.cylinder(radius=diameter / 2, height=h, sections=32)
    else:
        # BOX: extents=[X=width, Y=height, Z=depth]
        # Three.js Y-up: width→X축(좌우), height→Y축(수직), depth→Z축(앞뒤)
        mesh = trimesh.creation.box(extents=[w, h, d])

    # 비정상 비율 경고 (height가 width의 5배 이상이면 의심)
    if h > w * 5 and h > d * 5 and h > 1500:
        print(f"[GLBExporter] WARNING: {obj.get('object_type','?')} may be monolith — "
              f"w={w}, d={d}, h={h}. Check if height_mm/depth_mm are swapped in DB.")

    # Y축 기준 회전 (top-view)
    if rot_deg != 0:
        rot = trimesh.transformations.rotation_matrix(
            math.radians(-rot_deg), [0, 1, 0]
        )
        mesh.apply_transform(rot)

    # 위치: (-cx, h/2, cy) — X반전 (polygon과 동일 기준)
    mesh.apply_translation([-cx, h / 2, cy])

    # zone별 색상
    zone = obj.get("zone_label", "unknown")
    color = ZONE_COLORS.get(zone, ZONE_COLORS["unknown"])
    _apply_color(mesh, color)

    return mesh


def _get_ceiling_height(space_data: dict) -> float:
    ch = space_data.get("floor", {}).get("ceiling_height_mm", {})
    if isinstance(ch, dict):
        return ch.get("value", 3000)
    return 3000
