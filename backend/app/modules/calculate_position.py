"""
P0-5a — calculate_position 모듈

Agent 3의 direction 결정 + placement_slot 좌표 → 실제 Shapely Polygon 생성.
LLM 개입 없음. 순수 기하 연산.

direction별 전략:
  wall_facing: LineString.project() + interpolate()로 수선의 발 → depth/2 법선 오프셋
  inward:      격자점 = 중심, entrance 방향으로 Width Perpendicular 회전
  center:      격자점 = 중심, floor center 방향으로 Width Perpendicular 회전
  outward:     더미 (wall_facing과 동일 처리)
"""
import math
from typing import Optional

from shapely.affinity import rotate as shapely_rotate
from shapely.geometry import LineString, Point, Polygon, box

from app.schemas.placement import Placement


# 15° 안전장치 — rotation_deg와 코드 각도 차이가 이 값 미만이면 rotation_deg 무시
ROTATION_THRESHOLD_DEG = 15.0


def calculate_position(
    placement: Placement,
    slot: dict,
    obj: dict,
    space_data: dict,
) -> dict:
    """
    배치 좌표 계산 메인 함수.

    Args:
        placement: Agent 3 결정 (direction, rotation_deg 등)
        slot: placement_slot dict (x_mm, y_mm, wall_linestring, wall_normal)
        obj: eligible_object dict (width_mm, depth_mm, height_mm)
        space_data: 전체 공간 데이터

    Returns:
        {
            "center_x_mm": float,
            "center_y_mm": float,
            "rotation_deg": float,
            "bbox_polygon": Shapely Polygon,
            "width_mm": float,
            "depth_mm": float,
            "object_type": str,
        }
    """
    width = obj["width_mm"]
    depth = obj["depth_mm"]
    direction = placement.direction

    if direction == "wall_facing" or direction == "outward":
        center, code_angle = _wall_facing(slot, depth)
    elif direction == "inward":
        center, code_angle = _inward(slot, space_data)
    elif direction == "center":
        center, code_angle = _center(slot, space_data)
    else:
        center, code_angle = _wall_facing(slot, depth)

    # rotation_deg 15° 안전장치
    final_angle = _apply_rotation_override(code_angle, placement.rotation_deg)

    # Wall Snapping: 가장 가까운 벽 선분에 직교 정렬
    snapped_angle = _snap_to_nearest_wall(center, final_angle, space_data)

    # Shapely bbox polygon 생성
    bbox = _make_rotated_rect(center, width, depth, snapped_angle)

    result = {
        "center_x_mm": round(center[0], 1),
        "center_y_mm": round(center[1], 1),
        "rotation_deg": round(snapped_angle, 1),
        "bbox_polygon": bbox,
        "width_mm": width,
        "depth_mm": depth,
        "object_type": placement.object_type,
    }

    print(f"[CalcPos] {placement.object_type} → dir={direction}, "
          f"center=({result['center_x_mm']}, {result['center_y_mm']}), "
          f"code_angle={code_angle:.1f}°, snap={snapped_angle:.1f}°, "
          f"bbox={width}x{depth}mm")

    return result


# ── direction별 좌표 계산 ────────────────────────────────────────────────────

def _wall_facing(
    slot: dict,
    depth: float,
) -> tuple[tuple[float, float], float]:
    """
    wall_facing: 벽면에 등을 대고 정면이 내부를 향함.
    Issue 8 — LineString.project() + interpolate() 수선의 발.
    """
    wall_ls: LineString = slot["wall_linestring"]
    ref_point = Point(slot["x_mm"], slot["y_mm"])

    # 수선의 발 계산
    proj_dist = wall_ls.project(ref_point)
    foot = wall_ls.interpolate(proj_dist)

    # 벽 법선 방향 계산
    normal = slot["wall_normal"]
    nx, ny = _normal_to_vector(normal)

    # foot에서 법선 방향으로 depth/2 이동 → 오브젝트 중심
    cx = foot.x + nx * (depth / 2)
    cy = foot.y + ny * (depth / 2)

    # 회전각: 벽 방향 (법선의 90도 회전 = width가 벽을 따라 정렬)
    # 법선 (nx, ny) → 벽 방향 (-ny, nx)
    angle = math.degrees(math.atan2(nx, -ny))

    print(f"[CalcPos] wall_facing: foot=({foot.x:.0f},{foot.y:.0f}), "
          f"normal={normal}, wall_angle={angle:.1f}°, offset={depth/2:.0f}mm")

    return (cx, cy), angle


def _inward(
    slot: dict,
    space_data: dict,
) -> tuple[tuple[float, float], float]:
    """
    inward: slot 위치에서 entrance 방향을 바라봄.
    격자점 탐색: 법선 방향으로 step 간격 후보 생성 → floor 내부 필터.
    """
    nx, ny = _normal_to_vector(slot.get("wall_normal", "south"))
    floor_poly = space_data.get("floor", {}).get("polygon")
    entrance = _get_entrance(space_data)

    # 격자점 탐색: 법선 방향으로 여러 오프셋 시도
    candidates = _generate_normal_candidates(slot, nx, ny, floor_poly)

    if not candidates:
        # fallback: 고정 500mm
        cx = slot["x_mm"] + nx * 500
        cy = slot["y_mm"] + ny * 500
        candidates = [(cx, cy)]

    # entrance에 가장 가까운 후보 선택 (inward = 입구 쪽)
    if entrance:
        best = min(candidates, key=lambda c: math.hypot(c[0] - entrance[0], c[1] - entrance[1]))
        angle = math.degrees(math.atan2(entrance[1] - best[1], entrance[0] - best[0]))
    else:
        best = candidates[0]
        angle = 0.0

    print(f"[CalcPos] inward: center=({best[0]:.0f},{best[1]:.0f}), "
          f"entrance={entrance}, angle={angle:.1f}°, candidates={len(candidates)}")

    return best, angle


def _center(
    slot: dict,
    space_data: dict,
) -> tuple[tuple[float, float], float]:
    """
    center: slot 위치에서 floor center 방향을 바라봄.
    격자점 탐색: 법선 방향으로 step 간격 후보 생성 → floor 내부 필터.
    """
    nx, ny = _normal_to_vector(slot.get("wall_normal", "south"))
    floor_poly = space_data.get("floor", {}).get("polygon")

    candidates = _generate_normal_candidates(slot, nx, ny, floor_poly)

    if not candidates:
        cx = slot["x_mm"] + nx * 500
        cy = slot["y_mm"] + ny * 500
        candidates = [(cx, cy)]

    # floor centroid에 가장 가까운 후보 선택
    if floor_poly and hasattr(floor_poly, "centroid"):
        fc = floor_poly.centroid
        best = min(candidates, key=lambda c: math.hypot(c[0] - fc.x, c[1] - fc.y))
        angle = math.degrees(math.atan2(fc.y - best[1], fc.x - best[0]))
    else:
        best = candidates[0]
        angle = 0.0

    print(f"[CalcPos] center: center=({best[0]:.0f},{best[1]:.0f}), "
          f"angle={angle:.1f}°, candidates={len(candidates)}")

    return best, angle


def _generate_normal_candidates(
    slot: dict,
    nx: float,
    ny: float,
    floor_poly,
    max_steps: int = 8,
    step_base: float = 300,
) -> list[tuple[float, float]]:
    """
    법선 방향으로 step 간격 후보 격자점 생성.
    floor_polygon 내부인 점만 반환.
    """
    candidates = []
    sx, sy = slot["x_mm"], slot["y_mm"]

    for i in range(1, max_steps + 1):
        offset = step_base * i
        cx = sx + nx * offset
        cy = sy + ny * offset
        pt = Point(cx, cy)
        if floor_poly and floor_poly.contains(pt):
            candidates.append((cx, cy))

    # fallback: 격자점 0개 시 중앙 + 양 끝 3개 (설계 명세)
    if not candidates and floor_poly:
        mid_offset = step_base * (max_steps // 2)
        for off in [step_base, mid_offset, step_base * max_steps]:
            cx = sx + nx * off
            cy = sy + ny * off
            candidates.append((cx, cy))

    return candidates


# ── 회전 안전장치 ────────────────────────────────────────────────────────────

def _apply_rotation_override(
    code_angle: float,
    agent_rotation: Optional[float],
) -> float:
    """
    rotation_deg 15° 안전장치.
    Agent 3이 rotation_deg를 줬을 때:
      |rotation_deg - code_angle| >= 15° → Agent 3 각도 채택
      |rotation_deg - code_angle| < 15°  → 코드 각도 유지 (미세 변동 무시)
    """
    if agent_rotation is None:
        return code_angle

    diff = abs(_angle_diff(agent_rotation, code_angle))

    if diff >= ROTATION_THRESHOLD_DEG:
        print(f"[CalcPos] rotation override: code={code_angle:.1f}° → agent={agent_rotation:.1f}° (diff={diff:.1f}°)")
        return agent_rotation
    else:
        print(f"[CalcPos] rotation ignored: code={code_angle:.1f}°, agent={agent_rotation:.1f}° (diff={diff:.1f}° < {ROTATION_THRESHOLD_DEG}°)")
        return code_angle


def _angle_diff(a: float, b: float) -> float:
    """두 각도의 최소 차이 (0~180). 순환 각도 안전."""
    return abs(((a - b + 540) % 360) - 180)


def _snap_to_nearest_wall(
    center: tuple[float, float],
    angle: float,
    space_data: dict,
) -> float:
    """
    Wall Snapping: 배치 위치에서 가장 가까운 벽 선분의 각도를 기준으로
    평행/직교 4방향 중 code_angle에 가장 가까운 방향으로 snap.

    순환 각도 산술: (a - b + 540) % 360 - 180 으로 최단 차이 계산.
    """
    floor_poly = space_data.get("floor", {}).get("polygon")
    if not floor_poly or not hasattr(floor_poly, "exterior"):
        return _snap_ortho(angle)

    # 가장 가까운 외벽 선분 찾기
    center_pt = Point(center[0], center[1])
    coords = list(floor_poly.exterior.coords)
    best_wall_angle = None
    best_dist = float("inf")

    for i in range(len(coords) - 1):
        seg = LineString([coords[i], coords[i + 1]])
        d = seg.distance(center_pt)
        if d < best_dist:
            best_dist = d
            dx = coords[i + 1][0] - coords[i][0]
            dy = coords[i + 1][1] - coords[i][1]
            best_wall_angle = math.degrees(math.atan2(dy, dx))

    if best_wall_angle is None:
        return _snap_ortho(angle)

    # 벽 각도 기준 직교 4방향
    candidates = [(best_wall_angle + offset) % 360 for offset in [0, 90, 180, 270]]

    # code_angle에 가장 가까운 직교 방향 선택 (순환 안전)
    snapped = min(candidates, key=lambda c: _angle_diff(angle, c))

    return snapped


def _snap_ortho(angle: float) -> float:
    """벽 정보가 없을 때 0/90/180/270으로 snap."""
    candidates = [0, 90, 180, 270]
    return min(candidates, key=lambda c: _angle_diff(angle, c))


# ── 기하 헬퍼 ────────────────────────────────────────────────────────────────

def _make_rotated_rect(
    center: tuple[float, float],
    width: float,
    depth: float,
    angle_deg: float,
) -> Polygon:
    """중심 + width/depth + 회전각 → Shapely Polygon."""
    cx, cy = center
    half_w = width / 2
    half_d = depth / 2

    # 회전 전 축 정렬 bbox
    rect = box(cx - half_w, cy - half_d, cx + half_w, cy + half_d)

    # 중심 기준 회전
    if angle_deg != 0:
        rect = shapely_rotate(rect, angle_deg, origin=(cx, cy))

    return rect


def _normal_to_vector(normal: str) -> tuple[float, float]:
    """wall_normal 문자열 → 단위 벡터."""
    return {
        "north": (0.0, -1.0),
        "south": (0.0, 1.0),
        "east":  (1.0, 0.0),
        "west":  (-1.0, 0.0),
    }.get(normal, (0.0, -1.0))


def _get_entrance(space_data: dict) -> tuple[float, float] | None:
    """space_data에서 entrance mm 좌표 추출."""
    # Agent 2 back에서 entrance_mm을 저장하지 않으므로
    # slot들의 walk_mm=0인 지점을 entrance 근사로 사용
    min_walk = float("inf")
    entrance = None
    for key, val in space_data.items():
        if isinstance(val, dict) and "walk_mm" in val:
            wm = val["walk_mm"]
            if wm < min_walk:
                min_walk = wm
                entrance = (val.get("x_mm", 0), val.get("y_mm", 0))
    return entrance
