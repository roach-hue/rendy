import io
import re

import ezdxf
from ezdxf.math import Vec3

from app.parsers.base import FloorPlanParser
from app.schemas.drawings import (
    DetectedLineSegment,
    DetectedPoint,
    ParsedDrawings,
    ParsedFloorPlan,
    ParsedSection,
)

# 단면도 레이아웃/레이어 감지 키워드
SECTION_LAYOUT_KEYWORDS = re.compile(r"단면|section|s-\d", re.IGNORECASE)
SECTION_LAYER_KEYWORDS = re.compile(r"단면|section|s-", re.IGNORECASE)


class DXFParser(FloorPlanParser):
    """
    DXF 도면 파서 (ezdxf).
    - mm 단위 직접 추출 → scale_mm_per_px = 1.0 (픽셀 변환 불필요)
    - 레이아웃/레이어명으로 평면도·단면도 자동 구분
    - 천장 높이: TEXT/MTEXT 엔티티에서 숫자+mm 패턴 추출
    """

    async def parse(self) -> ParsedDrawings:
        doc = ezdxf.read(io.BytesIO(self.floor_bytes))

        floor_layout, section_layout = _split_layouts(doc)

        floor_plan = _parse_floor_layout(floor_layout or doc.modelspace())
        section = _parse_section_layout(section_layout) if section_layout else None

        # 단면도 파일이 별도로 넘어온 경우
        if self.section_bytes and section is None:
            section_doc = ezdxf.read(io.BytesIO(self.section_bytes))
            section = _parse_section_layout(section_doc.modelspace())

        return ParsedDrawings(floor_plan=floor_plan, section=section)


# ── 레이아웃 분리 ──────────────────────────────────────────────────────────

def _split_layouts(doc):
    """레이아웃 이름으로 평면도/단면도 구분. 없으면 (None, None)."""
    floor_layout = None
    section_layout = None

    for layout in doc.layouts:
        name = layout.name
        if SECTION_LAYOUT_KEYWORDS.search(name):
            section_layout = layout
        elif floor_layout is None and name != "Model":
            floor_layout = layout

    return floor_layout, section_layout


# ── 평면도 파싱 ────────────────────────────────────────────────────────────

def _parse_floor_layout(msp) -> ParsedFloorPlan:
    """modelspace 또는 평면도 레이아웃에서 polygon + 설비 추출."""
    floor_polygon_mm = _extract_outer_polygon(msp)
    inner_walls = _extract_inner_walls(msp)
    entrance = _extract_entrance(msp)

    entrance_width = _extract_entrance_width(msp)

    return ParsedFloorPlan(
        floor_polygon_px=floor_polygon_mm,   # DXF: mm = px (scale=1)
        scale_mm_per_px=1.0,
        entrance=entrance,
        entrance_width_mm=entrance_width,
        sprinklers=[],        # DXF에서 설비 심볼 감지는 별도 구현 필요 — 현재 미구현
        fire_hydrant=[],
        electrical_panel=[],
        inner_walls=inner_walls,
        inaccessible_rooms=[],
    )


def _extract_outer_polygon(msp) -> list[tuple[float, float]]:
    """LWPOLYLINE 중 최대 면적 → 외벽 polygon."""
    best = None
    best_area = 0.0

    for entity in msp.query("LWPOLYLINE"):
        pts = [(p[0], p[1]) for p in entity.get_points()]
        if len(pts) < 3:
            continue
        area = _polygon_area(pts)
        if area > best_area:
            best_area = area
            best = pts

    if best is None:
        # LWPOLYLINE 없으면 LINE 엔티티로 외곽 추정
        best = _lines_to_polygon(msp)

    if not best:
        raise ValueError("DXF에서 바닥 polygon 추출 실패 — LWPOLYLINE 또는 LINE 엔티티 없음")

    return best


def _lines_to_polygon(msp) -> list[tuple[float, float]]:
    """LINE 엔티티 끝점 수집 → 단순 convex hull 근사."""
    pts = []
    for entity in msp.query("LINE"):
        pts.append((entity.dxf.start.x, entity.dxf.start.y))
        pts.append((entity.dxf.end.x, entity.dxf.end.y))
    if not pts:
        return []
    # 중복 제거 후 외곽 bbox (정밀 hull은 P0-2 이후 개선)
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return [
        (min(xs), min(ys)),
        (max(xs), min(ys)),
        (max(xs), max(ys)),
        (min(xs), max(ys)),
    ]


def _extract_inner_walls(msp) -> list[DetectedLineSegment]:
    """레이어명 기준 내부 벽 LINE 추출."""
    segments = []
    for entity in msp.query("LINE LWPOLYLINE"):
        layer = entity.dxf.layer.upper()
        if any(kw in layer for kw in ("WALL", "벽", "PARTITION", "내벽")):
            if entity.dxftype() == "LINE":
                segments.append(DetectedLineSegment(
                    start_px=(entity.dxf.start.x, entity.dxf.start.y),
                    end_px=(entity.dxf.end.x, entity.dxf.end.y),
                    confidence="high",
                ))
    return segments


def _extract_entrance(msp) -> DetectedPoint | None:
    """레이어명 또는 블록명으로 입구 위치 추출."""
    for entity in msp.query("INSERT"):
        name = (entity.dxf.name or "").upper()
        layer = entity.dxf.layer.upper()
        if any(kw in name or kw in layer for kw in ("DOOR", "문", "ENTRANCE", "입구")):
            pt = entity.dxf.insert
            return DetectedPoint(x_px=pt.x, y_px=pt.y, confidence="high")
    return None


def _extract_entrance_width(msp) -> float | None:
    """문(DOOR) INSERT 블록의 X 스케일로 입구 폭(mm) 추출."""
    for entity in msp.query("INSERT"):
        name = (entity.dxf.name or "").upper()
        layer = entity.dxf.layer.upper()
        if any(kw in name or kw in layer for kw in ("DOOR", "문", "ENTRANCE", "입구")):
            x_scale = getattr(entity.dxf, "xscale", 1.0)
            if x_scale and x_scale > 100:
                return float(x_scale)
    return None


# ── 단면도 파싱 ────────────────────────────────────────────────────────────

def _parse_section_layout(layout) -> ParsedSection | None:
    """단면도 레이아웃에서 ceiling_height_mm 추출."""
    ceiling_h = _extract_ceiling_height(layout)
    return ParsedSection(ceiling_height_mm=ceiling_h)


def _extract_ceiling_height(layout) -> float | None:
    """TEXT/MTEXT에서 숫자+mm 패턴으로 천장 높이 추출."""
    pattern = re.compile(r"(\d{3,5})\s*(?:mm)?", re.IGNORECASE)
    candidates = []

    for entity in layout.query("TEXT MTEXT"):
        text = getattr(entity.dxf, "text", "") or ""
        lower = text.lower()
        # 천장 높이 관련 키워드가 있는 텍스트만
        if any(kw in lower for kw in ("천장", "ceiling", "ch", "층고")):
            for m in pattern.finditer(text):
                val = float(m.group(1))
                if 1800 <= val <= 10000:
                    candidates.append(val)

    return candidates[0] if candidates else None


# ── 유틸 ──────────────────────────────────────────────────────────────────

def _polygon_area(pts: list[tuple[float, float]]) -> float:
    """Shoelace 공식으로 polygon 면적 계산."""
    n = len(pts)
    area = 0.0
    for i in range(n):
        j = (i + 1) % n
        area += pts[i][0] * pts[j][1]
        area -= pts[j][0] * pts[i][1]
    return abs(area) / 2.0
