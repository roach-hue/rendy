"""
DXF 도면 파서 — ezdxf 기반 정밀 추출.

mm 단위 직접 추출 → scale_mm_per_px = 1.0 (픽셀 변환 불필요).
레이아웃/레이어명으로 평면도·단면도 자동 구분.

공학적 안전장치:
  1. 절대 좌표계 정규화: 전체 BBox min → (0,0) 오프셋
  2. 스냅 톨러런스: 끝점 5mm 이내 → 단일 좌표 병합 (polygonize 실패 방지)
  3. ARC/CIRCLE 테셀레이션: CHORD_TOLERANCE=50mm 기반 다점 변환
  4. TEXT 앵커링 + 2000×2000mm 고정 폴백 (inaccessible_rooms)
"""
import math
import os
import re
import tempfile
from typing import Optional

import ezdxf
from shapely.geometry import LineString, MultiLineString, Polygon
from shapely.ops import polygonize, snap, unary_union

from app.parsers.base import FloorPlanParser
from app.schemas.drawings import (
    DetectedEntrance,
    DetectedLineSegment,
    DetectedPoint,
    DetectedPolygon,
    ParsedDrawings,
    ParsedFloorPlan,
    ParsedSection,
)


# ── 상수 ──────────────────────────────────────────────────────────────────────

# 단면도 레이아웃/레이어 감지 키워드
SECTION_LAYOUT_KEYWORDS = re.compile(r"단면|section|s-\d", re.IGNORECASE)

# 스냅 톨러런스 (mm) — 끝점 간 5mm 이내 → 병합
SNAP_TOLERANCE_MM = 5.0

# ARC 테셀레이션 — 현(chord) 오차 허용치 (mm)
CHORD_TOLERANCE_MM = 50.0

# ARC 테셀레이션 최소/최대 세그먼트 수
ARC_MIN_SEGMENTS = 8
ARC_MAX_SEGMENTS = 128

# 접근 금지 구역 텍스트 → 폐합선 검색 실패 시 강제 생성할 폴백 사각형 크기
INACCESSIBLE_FALLBACK_SIZE_MM = 2000.0

# 접근 금지 구역 텍스트 주변 폐합선 탐색 반경 (mm)
INACCESSIBLE_SEARCH_RADIUS_MM = 5000.0

# 입구 텍스트 키워드
ENTRANCE_KEYWORDS = re.compile(
    r"entrance|입구|main\s*door|출입구", re.IGNORECASE
)
EMERGENCY_KEYWORDS = re.compile(
    r"emergency|비상구|비상\s*출구|fire\s*exit", re.IGNORECASE
)

# 접근 금지 구역 텍스트 키워드
INACCESSIBLE_KEYWORDS = re.compile(
    r"staff\s*only|staff\s*zone|staff\s*area|사무실|창고|화장실|기계실|전기실|계단실|"
    r"back\s*of\s*house|boh|storage|restroom|toilet|utility|mechanical|stairwell",
    re.IGNORECASE,
)

# INSERT 블록명/레이어명 기반 입구 감지
DOOR_KEYWORDS = re.compile(r"door|문|entrance|입구", re.IGNORECASE)

# 설비 심볼 패턴 (블록명 + 레이어명)
SPRINKLER_PATTERN = re.compile(r"sprinkler|sp\b|spk|스프링클러", re.IGNORECASE)
HYDRANT_PATTERN = re.compile(r"hydrant|fh\b|소화전|fire\s*hose", re.IGNORECASE)
ELEC_PANEL_PATTERN = re.compile(r"elec|mdp|분전반|eps|panel\b", re.IGNORECASE)

# 내부 벽 레이어 키워드
WALL_LAYER_KEYWORDS = ("WALL", "벽", "PARTITION", "내벽", "INTERIOR")


class DXFParser(FloorPlanParser):
    """
    DXF 도면 파서 (ezdxf).
    - mm 단위 직접 추출 → scale_mm_per_px = 1.0
    - ARC/CIRCLE → 다점 tessellation (CHORD_TOLERANCE=50mm)
    - TEXT/MTEXT → 입구, 접근 금지 구역 자동 앵커링
    - INSERT 블록 → 설비 심볼 감지
    - 안전장치: 좌표 정규화, 스냅 톨러런스, 폴백 사각형
    """

    async def parse(self) -> ParsedDrawings:
        # ezdxf.readfile이 인코딩/CRLF를 자동 처리 — 임시 파일 경유
        doc = _read_dxf_bytes(self.floor_bytes)

        floor_layout, section_layout = _split_layouts(doc)
        msp = floor_layout or doc.modelspace()

        # ── 전체 엔티티에서 선분 수집 ─────────────────────────────────────
        raw_segments = _collect_all_segments(msp)

        # ── 안전장치 1: 절대 좌표계 정규화 ────────────────────────────────
        all_points = []
        for seg in raw_segments:
            all_points.extend(seg)
        offset_x, offset_y = _compute_origin_offset(all_points)

        normalized_segments = [
            [(x - offset_x, y - offset_y) for x, y in seg]
            for seg in raw_segments
        ]

        # ── 안전장치 2: 스냅 톨러런스 전처리 ──────────────────────────────
        snapped_segments = _snap_endpoints(normalized_segments, SNAP_TOLERANCE_MM)

        # ── 외벽 polygon 추출 (polygonize) ────────────────────────────────
        floor_polygon = _build_outer_polygon(snapped_segments)

        if not floor_polygon:
            # 최종 폴백: LWPOLYLINE 최대 면적 (정규화 적용)
            floor_polygon = _extract_lwpolyline_polygon(msp, offset_x, offset_y)

        if not floor_polygon:
            raise ValueError(
                "DXF에서 바닥 polygon 추출 실패 — "
                "LINE, ARC, LWPOLYLINE 어느 것으로도 폐합 영역을 구성할 수 없습니다"
            )

        # ── 내부 벽 추출 ──────────────────────────────────────────────────
        inner_walls = _extract_inner_walls(msp, offset_x, offset_y)

        # ── TEXT/MTEXT 앵커링 ─────────────────────────────────────────────
        entrances = _extract_entrances_from_text(msp, offset_x, offset_y)
        inaccessible = _extract_inaccessible_from_text(
            msp, offset_x, offset_y, snapped_segments
        )

        # ── INSERT 블록 입구 감지 (TEXT에서 못 찾은 경우 보완) ──────────────
        insert_entrances = _extract_entrances_from_inserts(msp, offset_x, offset_y)
        if not entrances and insert_entrances:
            entrances = insert_entrances
        elif insert_entrances:
            # TEXT 기반과 INSERT 기반 병합 (중복 제거: 500mm 이내 동일 취급)
            for ie in insert_entrances:
                is_dup = any(
                    math.hypot(ie.x_px - e.x_px, ie.y_px - e.y_px) < 500
                    for e in entrances
                )
                if not is_dup:
                    entrances.append(ie)

        entrance_width = _extract_entrance_width(msp)

        # ── 설비 심볼 추출 ────────────────────────────────────────────────
        sprinklers = _extract_equipment(msp, SPRINKLER_PATTERN, offset_x, offset_y)
        hydrants = _extract_equipment(msp, HYDRANT_PATTERN, offset_x, offset_y)
        panels = _extract_equipment(msp, ELEC_PANEL_PATTERN, offset_x, offset_y)

        # ── 도면 치수 추출 ────────────────────────────────────────────────
        poly_coords = floor_polygon
        xs = [p[0] for p in poly_coords]
        ys = [p[1] for p in poly_coords]
        detected_w = max(xs) - min(xs)
        detected_h = max(ys) - min(ys)

        # ── 단면도 파싱 ──────────────────────────────────────────────────
        section = _parse_section_layout(section_layout) if section_layout else None
        if self.section_bytes and section is None:
            section_doc = _read_dxf_bytes(self.section_bytes)
            section = _parse_section_layout(section_doc.modelspace())

        # ── 출력 조립 (ParsedDrawings 스키마 100% 준수) ──────────────────
        floor_plan = ParsedFloorPlan(
            floor_polygon_px=floor_polygon,
            scale_mm_per_px=1.0,
            scale_confirmed=True,
            detected_width_mm=round(detected_w, 1),
            detected_height_mm=round(detected_h, 1),
            entrance=DetectedPoint(
                x_px=entrances[0].x_px,
                y_px=entrances[0].y_px,
                confidence=entrances[0].confidence,
            ) if entrances else None,
            entrances=entrances,
            entrance_width_mm=entrance_width,
            sprinklers=sprinklers,
            fire_hydrant=hydrants,
            electrical_panel=panels,
            inner_walls=inner_walls,
            inaccessible_rooms=inaccessible,
        )

        print(
            f"[DXFParser] polygon={len(floor_polygon)}pts, "
            f"entrances={len(entrances)}, "
            f"inaccessible={len(inaccessible)}, "
            f"equipment={len(sprinklers)}sp+{len(hydrants)}fh+{len(panels)}ep, "
            f"inner_walls={len(inner_walls)}, "
            f"dims={detected_w:.0f}x{detected_h:.0f}mm, "
            f"offset=({offset_x:.0f},{offset_y:.0f})"
        )

        return ParsedDrawings(floor_plan=floor_plan, section=section)


# ══════════════════════════════════════════════════════════════════════════════
# 안전장치 1 — 절대 좌표계 정규화
# ══════════════════════════════════════════════════════════════════════════════

def _compute_origin_offset(
    points: list[tuple[float, float]],
) -> tuple[float, float]:
    """전체 좌표의 BBox 최솟값을 반환. 빈 리스트면 (0, 0)."""
    if not points:
        return 0.0, 0.0
    min_x = min(p[0] for p in points)
    min_y = min(p[1] for p in points)
    return min_x, min_y


# ══════════════════════════════════════════════════════════════════════════════
# 안전장치 2 — 스냅 톨러런스 전처리
# ══════════════════════════════════════════════════════════════════════════════

def _snap_endpoints(
    segments: list[list[tuple[float, float]]],
    tolerance: float,
) -> list[list[tuple[float, float]]]:
    """
    선분 끝점 간 거리가 tolerance 이하이면 동일 좌표로 병합.
    polygonize() 폐합 실패를 물리적으로 차단.
    """
    # 모든 끝점 수집 (선분의 첫/끝 점)
    all_endpoints: list[list[float]] = []
    for seg in segments:
        if len(seg) >= 2:
            all_endpoints.append(list(seg[0]))
            all_endpoints.append(list(seg[-1]))

    # 그리디 병합: 가까운 점들을 대표점으로 통합
    merged_map: dict[int, tuple[float, float]] = {}
    n = len(all_endpoints)
    visited = [False] * n

    for i in range(n):
        if visited[i]:
            continue
        cluster = [i]
        visited[i] = True
        for j in range(i + 1, n):
            if visited[j]:
                continue
            dx = all_endpoints[i][0] - all_endpoints[j][0]
            dy = all_endpoints[i][1] - all_endpoints[j][1]
            if math.hypot(dx, dy) <= tolerance:
                cluster.append(j)
                visited[j] = True

        # 대표점: 클러스터 평균
        avg_x = sum(all_endpoints[k][0] for k in cluster) / len(cluster)
        avg_y = sum(all_endpoints[k][1] for k in cluster) / len(cluster)
        rep = (round(avg_x, 1), round(avg_y, 1))
        for k in cluster:
            merged_map[k] = rep

    # 끝점 인덱스 매핑 재구성
    endpoint_idx = 0
    result: list[list[tuple[float, float]]] = []

    for seg in segments:
        if len(seg) < 2:
            continue

        new_seg = list(seg)
        # 첫 점 스냅
        if endpoint_idx in merged_map:
            new_seg[0] = merged_map[endpoint_idx]
        endpoint_idx += 1

        # 끝 점 스냅
        if endpoint_idx in merged_map:
            new_seg[-1] = merged_map[endpoint_idx]
        endpoint_idx += 1

        # 퇴화 선분 제거 (스냅 후 시작=끝)
        if len(new_seg) == 2 and new_seg[0] == new_seg[-1]:
            continue

        result.append(new_seg)

    return result


# ══════════════════════════════════════════════════════════════════════════════
# ARC/CIRCLE 테셀레이션
# ══════════════════════════════════════════════════════════════════════════════

def _tessellate_arc(
    cx: float, cy: float,
    radius: float,
    start_angle_deg: float,
    end_angle_deg: float,
) -> list[tuple[float, float]]:
    """
    ARC → 다점 좌표 배열 변환.

    세그먼트 수 산출:
      arc_length = radius × |Δθ|
      N = max(ARC_MIN_SEGMENTS, arc_length / CHORD_TOLERANCE_MM)
      N = min(N, ARC_MAX_SEGMENTS)
    """
    start_rad = math.radians(start_angle_deg)
    end_rad = math.radians(end_angle_deg)

    # ezdxf ARC: start < end (반시계 방향). 역전 시 보정.
    if end_rad < start_rad:
        end_rad += 2 * math.pi

    delta = end_rad - start_rad
    arc_length = radius * abs(delta)

    n = max(ARC_MIN_SEGMENTS, int(arc_length / CHORD_TOLERANCE_MM))
    n = min(n, ARC_MAX_SEGMENTS)

    points = []
    for i in range(n + 1):
        theta = start_rad + delta * i / n
        x = cx + radius * math.cos(theta)
        y = cy + radius * math.sin(theta)
        points.append((round(x, 1), round(y, 1)))

    return points


def _tessellate_circle(
    cx: float, cy: float, radius: float,
) -> list[tuple[float, float]]:
    """CIRCLE → 폐합 다점 좌표 배열."""
    return _tessellate_arc(cx, cy, radius, 0, 360)


# ══════════════════════════════════════════════════════════════════════════════
# 선분 수집 (LINE + LWPOLYLINE + ARC + CIRCLE)
# ══════════════════════════════════════════════════════════════════════════════

def _collect_all_segments(msp) -> list[list[tuple[float, float]]]:
    """
    모델스페이스의 모든 선형 엔티티를 2D 선분(점 배열)으로 수집.
    ARC/CIRCLE은 tessellation 적용.
    LWPOLYLINE의 bulge(원호 세그먼트)도 tessellation 적용.
    """
    segments: list[list[tuple[float, float]]] = []

    for entity in msp:
        dxf_type = entity.dxftype()

        if dxf_type == "LINE":
            s = entity.dxf.start
            e = entity.dxf.end
            segments.append([
                (round(s.x, 1), round(s.y, 1)),
                (round(e.x, 1), round(e.y, 1)),
            ])

        elif dxf_type == "LWPOLYLINE":
            pts = list(entity.get_points(format="xyseb"))
            if len(pts) < 2:
                continue
            poly_pts: list[tuple[float, float]] = []

            for i in range(len(pts)):
                x1, y1 = pts[i][0], pts[i][1]
                bulge = pts[i][4] if len(pts[i]) > 4 else 0.0

                poly_pts.append((round(x1, 1), round(y1, 1)))

                # bulge != 0 → 원호 세그먼트
                if bulge != 0 and i < len(pts) - 1:
                    x2, y2 = pts[i + 1][0], pts[i + 1][1]
                    arc_pts = _bulge_to_arc_points(
                        x1, y1, x2, y2, bulge
                    )
                    # 첫/끝 점 제외 (인접 세그먼트와 중복)
                    if len(arc_pts) > 2:
                        poly_pts.extend(arc_pts[1:-1])

            # 폐합 처리
            if entity.closed and len(poly_pts) >= 3:
                # 마지막 → 첫 번째 bulge 처리
                last_bulge = pts[-1][4] if len(pts[-1]) > 4 else 0.0
                if last_bulge != 0:
                    arc_pts = _bulge_to_arc_points(
                        pts[-1][0], pts[-1][1],
                        pts[0][0], pts[0][1],
                        last_bulge,
                    )
                    if len(arc_pts) > 2:
                        poly_pts.extend(arc_pts[1:-1])
                poly_pts.append(poly_pts[0])  # 폐합

            if len(poly_pts) >= 2:
                segments.append(poly_pts)

        elif dxf_type == "ARC":
            cx = entity.dxf.center.x
            cy = entity.dxf.center.y
            r = entity.dxf.radius
            sa = entity.dxf.start_angle
            ea = entity.dxf.end_angle
            arc_pts = _tessellate_arc(cx, cy, r, sa, ea)
            if len(arc_pts) >= 2:
                segments.append(arc_pts)

        elif dxf_type == "CIRCLE":
            cx = entity.dxf.center.x
            cy = entity.dxf.center.y
            r = entity.dxf.radius
            circle_pts = _tessellate_circle(cx, cy, r)
            if len(circle_pts) >= 2:
                segments.append(circle_pts)

    return segments


def _bulge_to_arc_points(
    x1: float, y1: float,
    x2: float, y2: float,
    bulge: float,
) -> list[tuple[float, float]]:
    """
    LWPOLYLINE bulge 값 → 원호 좌표 배열.

    bulge = tan(included_angle / 4)
    양수: 반시계, 음수: 시계
    """
    dx = x2 - x1
    dy = y2 - y1
    chord = math.hypot(dx, dy)
    if chord < 0.01:
        return [(x1, y1), (x2, y2)]

    # 호 파라미터 계산
    sagitta = abs(bulge) * chord / 2
    radius = (chord**2 / 4 + sagitta**2) / (2 * sagitta)

    # 현 중점
    mx = (x1 + x2) / 2
    my = (y1 + y2) / 2

    # 현에 수직인 방향 (중심 방향)
    nx = -dy / chord
    ny = dx / chord

    # 중심에서 현 중점까지 거리
    d = radius - sagitta

    # bulge 부호에 따라 중심 방향 결정
    # DXF 규약: bulge > 0 → 진행 방향(P1→P2) 기준 좌측에 호가 볼록
    # normal (nx, ny) = (-dy, dx)/chord → 진행 방향 기준 좌측
    # 중심은 호의 반대쪽이므로 bulge > 0일 때 -normal 방향
    if bulge > 0:
        cx = mx - d * nx
        cy = my - d * ny
    else:
        cx = mx + d * nx
        cy = my + d * ny

    # 시작/끝 각도
    sa = math.atan2(y1 - cy, x1 - cx)
    ea = math.atan2(y2 - cy, x2 - cx)

    # bulge 방향에 따른 각도 조정
    # DXF bulge > 0: P1→P2 기준 좌측 볼록 → 반시계 방향 sweep
    # 그러나 중심이 -normal 쪽에 있으므로 sa→ea는 시계 방향(감소)
    if bulge > 0:
        if ea > sa:
            ea -= 2 * math.pi
    else:
        if ea < sa:
            ea += 2 * math.pi

    # 테셀레이션
    arc_length = abs(radius * (ea - sa))
    n = max(ARC_MIN_SEGMENTS, int(arc_length / CHORD_TOLERANCE_MM))
    n = min(n, ARC_MAX_SEGMENTS)

    points = []
    for i in range(n + 1):
        t = sa + (ea - sa) * i / n
        x = cx + radius * math.cos(t)
        y = cy + radius * math.sin(t)
        points.append((round(x, 1), round(y, 1)))

    return points


# ══════════════════════════════════════════════════════════════════════════════
# 외벽 polygon 구축
# ══════════════════════════════════════════════════════════════════════════════

def _build_outer_polygon(
    segments: list[list[tuple[float, float]]],
) -> list[tuple[float, float]] | None:
    """
    스냅 완료 선분 → Shapely polygonize → 최대 면적 polygon.
    """
    if not segments:
        return None

    lines = []
    for seg in segments:
        if len(seg) >= 2:
            try:
                ls = LineString(seg)
                if ls.is_valid and ls.length > 0:
                    lines.append(ls)
            except Exception:
                continue

    if not lines:
        return None

    # Shapely unary_union + polygonize
    merged = unary_union(lines)

    # snap으로 미세 갭 추가 보정
    if isinstance(merged, MultiLineString):
        merged = snap(merged, merged, SNAP_TOLERANCE_MM)

    polygons = list(polygonize(merged))

    if not polygons:
        # polygonize 실패 → convex hull 폴백
        print("[DXFParser] polygonize 실패 — convex hull 폴백")
        all_coords = []
        for seg in segments:
            all_coords.extend(seg)
        if len(all_coords) < 3:
            return None
        from shapely.geometry import MultiPoint
        hull = MultiPoint(all_coords).convex_hull
        if isinstance(hull, Polygon) and hull.area > 0:
            return list(hull.exterior.coords)
        return None

    # 최대 면적 polygon 선택
    best = max(polygons, key=lambda p: p.area)
    coords = list(best.exterior.coords)

    print(f"[DXFParser] polygonize: {len(polygons)} polygons, "
          f"best={best.area:.0f}mm², {len(coords)}pts")

    return [(round(x, 1), round(y, 1)) for x, y in coords]


def _extract_lwpolyline_polygon(
    msp, offset_x: float, offset_y: float,
) -> list[tuple[float, float]] | None:
    """LWPOLYLINE 최대 면적 폴백 (bulge tessellation 포함)."""
    best = None
    best_area = 0.0

    for entity in msp.query("LWPOLYLINE"):
        pts_raw = list(entity.get_points(format="xyseb"))
        if len(pts_raw) < 3:
            continue

        pts: list[tuple[float, float]] = []
        for i in range(len(pts_raw)):
            x1, y1 = pts_raw[i][0], pts_raw[i][1]
            bulge = pts_raw[i][4] if len(pts_raw[i]) > 4 else 0.0

            pts.append((
                round(x1 - offset_x, 1),
                round(y1 - offset_y, 1),
            ))

            if bulge != 0 and i < len(pts_raw) - 1:
                x2, y2 = pts_raw[i + 1][0], pts_raw[i + 1][1]
                arc_pts = _bulge_to_arc_points(x1, y1, x2, y2, bulge)
                for ap in arc_pts[1:-1]:
                    pts.append((
                        round(ap[0] - offset_x, 1),
                        round(ap[1] - offset_y, 1),
                    ))

        area = _polygon_area(pts)
        if area > best_area:
            best_area = area
            best = pts

    return best


# ══════════════════════════════════════════════════════════════════════════════
# 내부 벽 추출
# ══════════════════════════════════════════════════════════════════════════════

def _extract_inner_walls(
    msp, offset_x: float, offset_y: float,
) -> list[DetectedLineSegment]:
    """레이어명 기준 내부 벽 LINE/LWPOLYLINE 추출."""
    segments = []

    for entity in msp.query("LINE LWPOLYLINE"):
        layer = entity.dxf.layer.upper()
        if not any(kw in layer for kw in WALL_LAYER_KEYWORDS):
            continue

        if entity.dxftype() == "LINE":
            s = entity.dxf.start
            e = entity.dxf.end
            segments.append(DetectedLineSegment(
                start_px=(
                    round(s.x - offset_x, 1),
                    round(s.y - offset_y, 1),
                ),
                end_px=(
                    round(e.x - offset_x, 1),
                    round(e.y - offset_y, 1),
                ),
                confidence="high",
            ))

        elif entity.dxftype() == "LWPOLYLINE":
            pts = [(p[0], p[1]) for p in entity.get_points()]
            for i in range(len(pts) - 1):
                segments.append(DetectedLineSegment(
                    start_px=(
                        round(pts[i][0] - offset_x, 1),
                        round(pts[i][1] - offset_y, 1),
                    ),
                    end_px=(
                        round(pts[i + 1][0] - offset_x, 1),
                        round(pts[i + 1][1] - offset_y, 1),
                    ),
                    confidence="high",
                ))

    return segments


# ══════════════════════════════════════════════════════════════════════════════
# TEXT/MTEXT 앵커링 — 입구
# ══════════════════════════════════════════════════════════════════════════════

def _extract_entrances_from_text(
    msp, offset_x: float, offset_y: float,
) -> list[DetectedEntrance]:
    """TEXT/MTEXT에서 ENTRANCE/비상구 키워드 → DetectedEntrance."""
    entrances: list[DetectedEntrance] = []

    for entity in msp.query("TEXT MTEXT"):
        text = _get_entity_text(entity)
        if not text:
            continue

        insert = _get_entity_insert(entity)
        if insert is None:
            continue

        x = round(insert[0] - offset_x, 1)
        y = round(insert[1] - offset_y, 1)

        if EMERGENCY_KEYWORDS.search(text):
            entrances.append(DetectedEntrance(
                x_px=x, y_px=y,
                confidence="high",
                is_main=False,
                type="EMERGENCY_EXIT",
            ))
        elif ENTRANCE_KEYWORDS.search(text):
            entrances.append(DetectedEntrance(
                x_px=x, y_px=y,
                confidence="high",
                is_main=True,
                type="MAIN_DOOR",
            ))

    return entrances


# ══════════════════════════════════════════════════════════════════════════════
# TEXT/MTEXT 앵커링 — 접근 금지 구역 + 폴백 사각형
# ══════════════════════════════════════════════════════════════════════════════

def _extract_inaccessible_from_text(
    msp,
    offset_x: float,
    offset_y: float,
    all_segments: list[list[tuple[float, float]]],
) -> list[DetectedPolygon]:
    """
    TEXT/MTEXT에서 STAFF ONLY 등 감지 → 주변 폐합선 탐색.
    폐합선 없으면 2000×2000mm 폴백 사각형 강제 생성.
    """
    results: list[DetectedPolygon] = []

    for entity in msp.query("TEXT MTEXT"):
        text = _get_entity_text(entity)
        if not text or not INACCESSIBLE_KEYWORDS.search(text):
            continue

        insert = _get_entity_insert(entity)
        if insert is None:
            continue

        tx = round(insert[0] - offset_x, 1)
        ty = round(insert[1] - offset_y, 1)

        # 주변 폐합 polygon 탐색
        enclosing = _find_enclosing_polygon(tx, ty, all_segments)

        if enclosing:
            results.append(DetectedPolygon(
                polygon_px=enclosing,
                confidence="high",
            ))
            print(f"[DXFParser] inaccessible '{text.strip()}' → "
                  f"enclosing polygon {len(enclosing)}pts")
        else:
            # 안전장치 4: 폴백 사각형 (2000×2000mm)
            half = INACCESSIBLE_FALLBACK_SIZE_MM / 2
            fallback_poly = [
                (tx - half, ty - half),
                (tx + half, ty - half),
                (tx + half, ty + half),
                (tx - half, ty + half),
                (tx - half, ty - half),
            ]
            results.append(DetectedPolygon(
                polygon_px=fallback_poly,
                confidence="medium",
            ))
            print(f"[DXFParser] inaccessible '{text.strip()}' → "
                  f"fallback {INACCESSIBLE_FALLBACK_SIZE_MM:.0f}mm square "
                  f"at ({tx:.0f},{ty:.0f})")

    return results


def _find_enclosing_polygon(
    tx: float, ty: float,
    segments: list[list[tuple[float, float]]],
) -> list[tuple[float, float]] | None:
    """
    (tx, ty) 좌표를 포함하는 가장 작은 폐합 polygon 탐색.
    전체 선분에서 polygonize 후 point-in-polygon 체크.
    """
    from shapely.geometry import Point

    lines = []
    for seg in segments:
        if len(seg) >= 2:
            try:
                ls = LineString(seg)
                if ls.is_valid and ls.length > 0:
                    lines.append(ls)
            except Exception:
                continue

    if not lines:
        return None

    merged = unary_union(lines)
    polygons = list(polygonize(merged))

    point = Point(tx, ty)
    candidates = [p for p in polygons if p.contains(point)]

    if not candidates:
        # point 근처 polygon 탐색 (텍스트가 polygon 경계에 걸칠 수 있음)
        candidates = [
            p for p in polygons
            if p.distance(point) < INACCESSIBLE_SEARCH_RADIUS_MM
            and p.area < 50_000_000  # 50m² 이하만 (전체 바닥 제외)
        ]

    if not candidates:
        return None

    # 가장 작은 polygon (전체 바닥이 아닌 실제 구획)
    best = min(candidates, key=lambda p: p.area)
    coords = list(best.exterior.coords)
    return [(round(x, 1), round(y, 1)) for x, y in coords]


# ══════════════════════════════════════════════════════════════════════════════
# INSERT 블록 — 입구 감지
# ══════════════════════════════════════════════════════════════════════════════

def _extract_entrances_from_inserts(
    msp, offset_x: float, offset_y: float,
) -> list[DetectedEntrance]:
    """INSERT 블록명/레이어명으로 입구 위치 추출."""
    entrances: list[DetectedEntrance] = []

    for entity in msp.query("INSERT"):
        name = (entity.dxf.name or "").upper()
        layer = entity.dxf.layer.upper()
        combined = f"{name} {layer}"

        if not DOOR_KEYWORDS.search(combined):
            continue

        pt = entity.dxf.insert
        x = round(pt.x - offset_x, 1)
        y = round(pt.y - offset_y, 1)

        is_emergency = EMERGENCY_KEYWORDS.search(combined)
        entrances.append(DetectedEntrance(
            x_px=x,
            y_px=y,
            confidence="high",
            is_main=not is_emergency,
            type="EMERGENCY_EXIT" if is_emergency else "MAIN_DOOR",
        ))

    return entrances


def _extract_entrance_width(msp) -> Optional[float]:
    """DOOR INSERT 블록의 X 스케일로 입구 폭(mm) 추출."""
    for entity in msp.query("INSERT"):
        name = (entity.dxf.name or "").upper()
        layer = entity.dxf.layer.upper()
        if DOOR_KEYWORDS.search(f"{name} {layer}"):
            x_scale = getattr(entity.dxf, "xscale", 1.0)
            if x_scale and x_scale > 100:
                return float(x_scale)
    return None


# ══════════════════════════════════════════════════════════════════════════════
# 설비 심볼 추출
# ══════════════════════════════════════════════════════════════════════════════

def _extract_equipment(
    msp,
    pattern: re.Pattern,
    offset_x: float,
    offset_y: float,
) -> list[DetectedPoint]:
    """INSERT 블록명 + 레이어명 패턴 매칭으로 설비 중심점 추출."""
    points: list[DetectedPoint] = []

    for entity in msp.query("INSERT"):
        name = entity.dxf.name or ""
        layer = entity.dxf.layer or ""
        combined = f"{name} {layer}"

        if not pattern.search(combined):
            continue

        pt = entity.dxf.insert
        points.append(DetectedPoint(
            x_px=round(pt.x - offset_x, 1),
            y_px=round(pt.y - offset_y, 1),
            confidence="high",
        ))

    return points


# ══════════════════════════════════════════════════════════════════════════════
# 레이아웃 분리
# ══════════════════════════════════════════════════════════════════════════════

def _split_layouts(doc):
    """레이아웃 이름으로 평면도/단면도 구분. 빈 레이아웃은 무시."""
    floor_layout = None
    section_layout = None

    for layout in doc.layouts:
        name = layout.name
        if name == "Model":
            continue
        # 빈 레이아웃 무시 (Paper Space 기본 생성)
        entity_count = len(list(layout))
        if entity_count == 0:
            continue
        if SECTION_LAYOUT_KEYWORDS.search(name):
            section_layout = layout
        elif floor_layout is None:
            floor_layout = layout

    return floor_layout, section_layout


# ══════════════════════════════════════════════════════════════════════════════
# 단면도 파싱
# ══════════════════════════════════════════════════════════════════════════════

def _parse_section_layout(layout) -> Optional[ParsedSection]:
    """단면도 레이아웃에서 ceiling_height_mm 추출."""
    ceiling_h = _extract_ceiling_height(layout)
    return ParsedSection(ceiling_height_mm=ceiling_h)


def _extract_ceiling_height(layout) -> Optional[float]:
    """TEXT/MTEXT에서 숫자+mm 패턴으로 천장 높이 추출."""
    pattern = re.compile(r"(\d{3,5})\s*(?:mm)?", re.IGNORECASE)
    candidates = []

    for entity in layout.query("TEXT MTEXT"):
        text = _get_entity_text(entity)
        if not text:
            continue
        lower = text.lower()
        if any(kw in lower for kw in ("천장", "ceiling", "ch", "층고")):
            for m in pattern.finditer(text):
                val = float(m.group(1))
                if 1800 <= val <= 10000:
                    candidates.append(val)

    return candidates[0] if candidates else None


# ══════════════════════════════════════════════════════════════════════════════
# 유틸리티
# ══════════════════════════════════════════════════════════════════════════════

def _get_entity_text(entity) -> str:
    """TEXT/MTEXT 엔티티에서 텍스트 추출 (MTEXT 포맷 코드 제거)."""
    if entity.dxftype() == "MTEXT":
        # MTEXT는 .text에 포맷 코드 포함 가능 → plain_text() 사용
        try:
            return entity.plain_text()
        except Exception:
            return getattr(entity.dxf, "text", "") or ""
    return getattr(entity.dxf, "text", "") or ""


def _get_entity_insert(entity) -> Optional[tuple[float, float]]:
    """TEXT/MTEXT 엔티티의 삽입점 좌표 추출."""
    try:
        insert = entity.dxf.insert
        return (insert.x, insert.y)
    except AttributeError:
        return None


def _read_dxf_bytes(data: bytes):
    """
    bytes → ezdxf Document.
    ezdxf.readfile()이 인코딩(ANSI_1252 등)/CRLF를 자동 처리하므로
    임시 파일 경유.
    """
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".dxf")
    try:
        with os.fdopen(tmp_fd, "wb") as f:
            f.write(data)
        return ezdxf.readfile(tmp_path)
    finally:
        os.unlink(tmp_path)


def _polygon_area(pts: list[tuple[float, float]]) -> float:
    """Shoelace 공식으로 polygon 면적 계산."""
    n = len(pts)
    area = 0.0
    for i in range(n):
        j = (i + 1) % n
        area += pts[i][0] * pts[j][1]
        area -= pts[j][0] * pts[i][1]
    return abs(area) / 2.0
