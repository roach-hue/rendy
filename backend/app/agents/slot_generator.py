"""Placement Slot 생성 — 외벽 edge slot + 내부 격자 interior slot."""
import math

from shapely.geometry import LineString, Point, Polygon


def max_object_width(poly: Polygon) -> float:
    """usable polygon 내 배치 가능한 최대 오브젝트 너비 (mm). bbox 단변의 40%."""
    minx, miny, maxx, maxy = poly.bounds
    short_side = min(maxx - minx, maxy - miny)
    return round(short_side * 0.4)


DECOMPRESSION_RADIUS_MM = 1500  # 기본값 — generate_edge_slots에서 도면 비례로 재계산


def generate_edge_slots(
    usable_poly: Polygon,
    dead_zones: list,
    entrances: list | None = None,
) -> dict[str, dict]:
    """
    외벽을 따라 step_mm 간격으로 placement_slot 생성.
    곡선 벽(조밀 좌표) 대응: 외벽 전체를 하나의 경로로 누적 순회하며
    step_mm 간격마다 slot 배치.
    전이 지대: 각 입구 반경 1500mm 내 슬롯 파괴.
    """
    coords = list(usable_poly.exterior.coords)
    slots: dict[str, dict] = {}

    max_w = max_object_width(usable_poly)
    step_mm = max(500, min(2000, int(math.sqrt(max_w**2 + max_w**2) * 0.7)))

    # 외벽 전체 둘레 길이
    exterior = usable_poly.exterior
    total_len = exterior.length

    print(f"[Agent2] polygon vertices: {len(coords)-1}, bounds: {usable_poly.bounds}, "
          f"step_mm={step_mm} (max_object_w={max_w}mm), perimeter={total_len:.0f}mm")

    # 전이 지대: 도면 비례 반경 (단변의 10%, 최소 500mm, 최대 2000mm)
    minx, miny, maxx, maxy = usable_poly.bounds
    short_side = min(maxx - minx, maxy - miny)
    decomp_radius = max(500, min(2000, short_side * 0.10))

    decompression_zones: list[Point] = []
    if entrances:
        for ent in entrances:
            ex = getattr(ent, "x_px", ent[0] if isinstance(ent, (list, tuple)) else 0)
            ey = getattr(ent, "y_px", ent[1] if isinstance(ent, (list, tuple)) else 0)
            decompression_zones.append(Point(ex, ey))
        print(f"[SlotGen] decompression zones: {len(decompression_zones)} entrances, radius={decomp_radius:.0f}mm (short_side={short_side:.0f}mm)")

    # 외벽 경로를 step_mm 간격으로 순회 (곡선 자동 추종)
    slot_idx = 0
    decompression_dropped = 0
    dist_along = step_mm

    while dist_along < total_len - step_mm * 0.5:
        pt_on_wall = exterior.interpolate(dist_along)
        x, y = pt_on_wall.x, pt_on_wall.y

        # Dead Zone 내부 제외
        if any(dz.contains(pt_on_wall) for dz in dead_zones):
            dist_along += step_mm
            continue

        # 전이 지대: 입구 반경 내 슬롯 파괴
        in_decompression = any(
            dz.distance(pt_on_wall) < decomp_radius
            for dz in decompression_zones
        )
        if in_decompression:
            decompression_dropped += 1
            dist_along += step_mm
            continue

        # 해당 위치의 세그먼트 찾기 → 법선 벡터 + 벽 각도 계산
        seg, seg_dx, seg_dy, seg_len = _find_segment_at(coords, dist_along, exterior)

        if seg_len > 0:
            nx_dir = -seg_dy / seg_len
            ny_dir = seg_dx / seg_len
            # 내부 방향 확인
            test_pt = Point(x + nx_dir * 100, y + ny_dir * 100)
            if not usable_poly.contains(test_pt):
                nx_dir, ny_dir = -nx_dir, -ny_dir
            wall_angle = math.degrees(math.atan2(seg_dy, seg_dx))
        else:
            nx_dir, ny_dir = 0.0, 1.0
            wall_angle = 0.0

        wall_name = _wall_direction_name(seg_dx, seg_dy)

        # 곡선 내측(concave) 간격 벌리기:
        # 인접 세그먼트 각도 변화량이 크면 step 확대
        actual_step = step_mm
        if slot_idx > 0:
            angle_change = _angle_change_at(coords, dist_along, exterior)
            if angle_change > 15:  # 15도 이상 꺾이면
                # 각도 변화에 비례해서 간격 확대 (최대 2배)
                factor = min(2.0, 1.0 + angle_change / 90.0)
                actual_step = step_mm * factor

        slot_key = f"{wall_name}_slot_{slot_idx}"
        slots[slot_key] = {
            "x_mm": round(x),
            "y_mm": round(y),
            "wall_linestring": seg if seg else LineString([(x, y), (x + 1, y)]),
            "wall_normal": _normal_label(nx_dir, ny_dir),
            "wall_normal_vec": (round(nx_dir, 4), round(ny_dir, 4)),
            "wall_angle_deg": round(wall_angle, 2),
            "zone_label": "entrance_zone",
            "shelf_capacity": _shelf_capacity(total_len / max(1, int(total_len / step_mm))),
            "walk_mm": 0.0,
        }
        slot_idx += 1
        dist_along += actual_step

    if decompression_dropped > 0:
        print(f"[SlotGen] decompression zone dropped: {decompression_dropped} slots")

    return slots


def _find_segment_at(
    coords: list[tuple[float, float]],
    dist_along: float,
    exterior,
) -> tuple[LineString | None, float, float, float]:
    """경로 위 거리에서 해당하는 세그먼트와 방향 벡터 반환."""
    cumulative = 0.0
    for i in range(len(coords) - 1):
        p1, p2 = coords[i], coords[i + 1]
        seg_len = math.hypot(p2[0] - p1[0], p2[1] - p1[1])
        if cumulative + seg_len >= dist_along:
            dx = p2[0] - p1[0]
            dy = p2[1] - p1[1]
            return LineString([p1, p2]), dx, dy, seg_len
        cumulative += seg_len
    # fallback: 마지막 세그먼트
    p1, p2 = coords[-2], coords[-1]
    dx = p2[0] - p1[0]
    dy = p2[1] - p1[1]
    return LineString([p1, p2]), dx, dy, math.hypot(dx, dy)


def _angle_change_at(
    coords: list[tuple[float, float]],
    dist_along: float,
    exterior,
) -> float:
    """경로 위 거리에서 인접 세그먼트 간 각도 변화량 (도)."""
    cumulative = 0.0
    for i in range(len(coords) - 1):
        p1, p2 = coords[i], coords[i + 1]
        seg_len = math.hypot(p2[0] - p1[0], p2[1] - p1[1])
        if cumulative + seg_len >= dist_along and i > 0:
            # 이전 세그먼트 vs 현재 세그먼트 각도 차이
            prev_p1, prev_p2 = coords[i - 1], coords[i]
            prev_angle = math.degrees(math.atan2(prev_p2[1] - prev_p1[1], prev_p2[0] - prev_p1[0]))
            curr_angle = math.degrees(math.atan2(p2[1] - p1[1], p2[0] - p1[0]))
            diff = abs(((curr_angle - prev_angle + 540) % 360) - 180)
            return diff
        cumulative += seg_len
    return 0.0


def generate_interior_slots(
    usable_poly: Polygon,
    dead_zones: list,
    inner_walls: list[LineString],
    inner_wall_buffer_mm: float = 150,
    entrances: list | None = None,
) -> dict[str, dict]:
    """공간 내부 격자점에 interior_slot 생성. 전이 지대 내 슬롯 파괴."""
    max_w = max_object_width(usable_poly)
    step_mm = max(500, min(2000, int(math.sqrt(max_w**2 + max_w**2) * 0.7)))
    min_wall_dist = step_mm * 0.8

    minx, miny, maxx, maxy = usable_poly.bounds
    slots: dict[str, dict] = {}

    inner_wall_buffers = [w.buffer(inner_wall_buffer_mm) for w in inner_walls if w.length > 0]

    # 전이 지대: 도면 비례 반경 (단변의 10%, 최소 500mm, 최대 2000mm)
    short_side = min(maxx - minx, maxy - miny)
    decomp_radius = max(500, min(2000, short_side * 0.10))

    decomp_pts: list[Point] = []
    if entrances:
        for ent in entrances:
            ex = getattr(ent, "x_px", ent[0] if isinstance(ent, (list, tuple)) else 0)
            ey = getattr(ent, "y_px", ent[1] if isinstance(ent, (list, tuple)) else 0)
            decomp_pts.append(Point(ex, ey))

    exterior_coords = list(usable_poly.exterior.coords)
    all_segments: list[LineString] = []
    for i in range(len(exterior_coords) - 1):
        seg = LineString([exterior_coords[i], exterior_coords[i + 1]])
        if seg.length > 0:
            all_segments.append(seg)
    all_segments.extend(inner_walls)

    ix = 0
    for gx in _frange(minx + step_mm, maxx - step_mm, step_mm):
        for gy in _frange(miny + step_mm, maxy - step_mm, step_mm):
            pt = Point(gx, gy)
            if not usable_poly.contains(pt):
                continue
            if usable_poly.exterior.distance(pt) < min_wall_dist:
                continue
            # 전이 지대 내 슬롯 파괴
            if any(dp.distance(pt) < decomp_radius for dp in decomp_pts):
                continue
            if any(dz.contains(pt) for dz in dead_zones):
                continue
            if any(wb.contains(pt) for wb in inner_wall_buffers):
                continue

            nearest_seg = None
            nearest_dist = float("inf")
            nx_dir, ny_dir = 0.0, 1.0
            seg_len = 0.0
            for seg in all_segments:
                d = seg.distance(pt)
                if d < nearest_dist:
                    nearest_dist = d
                    nearest_seg = seg

            if nearest_seg:
                c0, c1 = nearest_seg.coords[0], nearest_seg.coords[1]
                dx = c1[0] - c0[0]
                dy = c1[1] - c0[1]
                seg_len = math.hypot(dx, dy)
                if seg_len > 0:
                    nx_dir = -dy / seg_len
                    ny_dir = dx / seg_len
                    test = Point(gx + nx_dir * 100, gy + ny_dir * 100)
                    if not usable_poly.contains(test):
                        nx_dir, ny_dir = -nx_dir, -ny_dir
                    normal_label = _normal_label(nx_dir, ny_dir)
                else:
                    normal_label = "north"
                    nearest_seg = LineString([(gx, gy), (gx + 1, gy)])
            else:
                normal_label = "north"
                nearest_seg = LineString([(gx, gy), (gx + 1, gy)])

            c0, c1 = nearest_seg.coords[0], nearest_seg.coords[1]
            i_wall_angle = math.degrees(math.atan2(c1[1] - c0[1], c1[0] - c0[0]))

            slots[f"interior_slot_{ix}"] = {
                "x_mm": round(gx),
                "y_mm": round(gy),
                "wall_linestring": nearest_seg,
                "wall_normal": normal_label,
                "wall_normal_vec": (round(nx_dir, 4), round(ny_dir, 4)) if seg_len > 0 else (0.0, -1.0),
                "wall_angle_deg": round(i_wall_angle, 2),
                "zone_label": "entrance_zone",
                "shelf_capacity": 1,
                "walk_mm": 0.0,
            }
            ix += 1

    return slots


# ── 헬퍼 ──────────────────────────────────────────────────────────────────────

def _wall_direction_name(dx: float, dy: float) -> str:
    if abs(dx) > abs(dy):
        return "south_wall" if dy >= 0 else "north_wall"
    return "east_wall" if dx >= 0 else "west_wall"


def _normal_label(nx_dir: float, ny_dir: float) -> str:
    """법선 벡터 → 방향 라벨 (Y-up 좌표계: +Y=north, -Y=south)."""
    if abs(nx_dir) > abs(ny_dir):
        return "east" if nx_dir > 0 else "west"
    return "north" if ny_dir > 0 else "south"


def _shelf_capacity(wall_len_mm: float) -> int:
    return max(1, int(wall_len_mm / 1200))


def _frange(start: float, stop: float, step: float) -> list[float]:
    result = []
    v = start
    while v <= stop:
        result.append(v)
        v += step
    return result
