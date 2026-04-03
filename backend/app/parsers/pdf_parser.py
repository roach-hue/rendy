"""
PDF 도면 파서 — 벡터 직접 추출 (pdfplumber)

전략:
  1. pdfplumber로 벡터 선분(lines, rects, curves) + 텍스트 직접 추출
  2. 벡터 데이터가 충분하면 DXFParser와 동일한 수준으로 기하학 데이터 구성
  3. 벡터 데이터가 없는 스캔 PDF(래스터 only)는 래스터화 후 ImageParser 위임

좌표계: PDF는 포인트(pt) 단위, 1pt = 1/72 inch ≈ 0.3528mm.
치수 텍스트에서 mm 값을 읽고 해당 선분의 pt 길이와 비교 → mm_per_pt 스케일 산출.
"""
import io
import math
import re
from typing import Optional

from app.parsers.base import FloorPlanParser
from app.schemas.drawings import (
    DetectedLineSegment,
    DetectedPoint,
    ParsedDrawings,
    ParsedFloorPlan,
    ParsedSection,
)

# 최소 벡터 선분 수 — 이 이하면 스캔 PDF로 판정하여 래스터 fallback
MIN_VECTOR_LINES = 10

# 치수 텍스트 패턴: 숫자 + 선택적 단위
_DIM_PATTERN = re.compile(r"(\d{3,6})\s*(?:mm)?", re.IGNORECASE)

# 입구 관련 키워드
_ENTRANCE_KEYWORDS = ("entrance", "입구", "door", "문", "출입")


class PDFParser(FloorPlanParser):
    """PDF 도면 파서 — 벡터 우선, 래스터 fallback."""

    async def parse(self) -> ParsedDrawings:
        import pdfplumber

        pdf = pdfplumber.open(io.BytesIO(self.floor_bytes))
        page = pdf.pages[0]

        lines = page.lines or []
        rects = page.rects or []
        chars = page.chars or []

        total_vectors = len(lines) + len(rects)
        print(f"[PDFParser] vectors: {len(lines)} lines, {len(rects)} rects, "
              f"{len(chars)} chars")

        if total_vectors < MIN_VECTOR_LINES:
            print(f"[PDFParser] too few vectors ({total_vectors}), falling back to raster")
            return await self._raster_fallback()

        # 벡터 직접 추출
        all_segments = _extract_segments(lines, rects, page.height)
        if not all_segments:
            print("[PDFParser] no valid segments, falling back to raster")
            return await self._raster_fallback()

        # 외벽 polygon 추출 (최대 면적 폐합)
        floor_polygon_pt = _find_outer_polygon(all_segments)
        if not floor_polygon_pt or len(floor_polygon_pt) < 3:
            print("[PDFParser] no floor polygon found, falling back to raster")
            return await self._raster_fallback()

        # 치수 텍스트에서 scale 계산
        dim_texts = _extract_dimension_texts(page, page.height)
        scale_mm_per_pt = _calc_scale(dim_texts, all_segments)

        # pt → mm 변환
        # scale_mm_per_px: 여기서 px = pt (PDF 좌표계)
        scale_mm_per_px = scale_mm_per_pt if scale_mm_per_pt else 0.3528  # fallback: 1pt ≈ 0.3528mm

        # 내부 벽 추출 (외벽 제외)
        inner_walls = _extract_inner_walls(all_segments, floor_polygon_pt)

        # 입구 추출
        entrance = _find_entrance(dim_texts, floor_polygon_pt)

        floor_plan = ParsedFloorPlan(
            floor_polygon_px=floor_polygon_pt,
            scale_mm_per_px=scale_mm_per_px,
            scale_confirmed=(scale_mm_per_pt is not None),
            detected_width_mm=_polygon_width(floor_polygon_pt) * scale_mm_per_px if scale_mm_per_pt else None,
            detected_height_mm=_polygon_height(floor_polygon_pt) * scale_mm_per_px if scale_mm_per_pt else None,
            entrance=entrance,
            sprinklers=[],
            fire_hydrant=[],
            electrical_panel=[],
            inner_walls=inner_walls,
            inaccessible_rooms=[],
        )

        section = None
        if self.section_bytes:
            section = await self._parse_section()

        print(f"[PDFParser] vector extraction OK: {len(floor_polygon_pt)} polygon pts, "
              f"scale={scale_mm_per_px:.4f} mm/pt, "
              f"{len(inner_walls)} inner walls, "
              f"entrance={'yes' if entrance else 'no'}")

        return ParsedDrawings(floor_plan=floor_plan, section=section)

    async def _raster_fallback(self) -> ParsedDrawings:
        """벡터 데이터 부족 시 래스터화 후 ImageParser 위임."""
        from app.parsers.image_parser import ImageParser, _parse_section_image

        floor_image = _rasterize_pdf(self.floor_bytes)
        image_parser = ImageParser(floor_image, section_bytes=None)
        result = await image_parser.parse()

        if self.section_bytes:
            section_image = _rasterize_pdf(self.section_bytes)
            result.section = _parse_section_image(section_image)

        return result

    async def _parse_section(self) -> Optional[ParsedSection]:
        """단면도 PDF에서 ceiling_height_mm 추출."""
        import pdfplumber

        try:
            pdf = pdfplumber.open(io.BytesIO(self.section_bytes))
            page = pdf.pages[0]
            text = page.extract_text() or ""

            for kw in ("천장", "ceiling", "ch", "층고"):
                if kw in text.lower():
                    for m in _DIM_PATTERN.finditer(text):
                        val = float(m.group(1))
                        if 1800 <= val <= 10000:
                            return ParsedSection(ceiling_height_mm=val)
        except Exception as e:
            print(f"[PDFParser] section parsing failed: {e}")

        return None


# ── 벡터 추출 ──────────────────────────────────────────────────────────────────

def _extract_segments(
    lines: list[dict],
    rects: list[dict],
    page_height: float,
) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    """pdfplumber lines + rects → 선분 리스트. Y축 반전(PDF는 하단=0)."""
    segments = []

    for ln in lines:
        x0, y0 = float(ln["x0"]), page_height - float(ln["top"])
        x1, y1 = float(ln["x1"]), page_height - float(ln["bottom"])
        if math.hypot(x1 - x0, y1 - y0) > 1:  # 1pt 미만 무시
            segments.append(((x0, y0), (x1, y1)))

    for rect in rects:
        x0 = float(rect["x0"])
        y0 = page_height - float(rect["top"])
        x1 = float(rect["x1"])
        y1 = page_height - float(rect["bottom"])
        # rect → 4변
        segments.append(((x0, y0), (x1, y0)))
        segments.append(((x1, y0), (x1, y1)))
        segments.append(((x1, y1), (x0, y1)))
        segments.append(((x0, y1), (x0, y0)))

    return segments


def _find_outer_polygon(
    segments: list[tuple[tuple[float, float], tuple[float, float]]],
) -> list[tuple[float, float]]:
    """
    선분들에서 최대 면적 폐합 다각형 추출.
    전략: 모든 끝점 수집 → convex hull → 내부 점 필터 → 단순화.
    """
    from shapely.geometry import MultiLineString, Polygon
    from shapely.ops import polygonize, unary_union

    if not segments:
        return []

    # 선분을 Shapely로 변환
    mls = MultiLineString(segments)
    merged = unary_union(mls)

    # polygonize: 닫힌 영역 추출
    polys = list(polygonize(merged))

    if not polys:
        # fallback: convex hull
        all_pts = []
        for (x0, y0), (x1, y1) in segments:
            all_pts.extend([(x0, y0), (x1, y1)])
        if len(all_pts) < 3:
            return []
        from shapely.geometry import MultiPoint
        hull = MultiPoint(all_pts).convex_hull
        if hasattr(hull, "exterior"):
            return list(hull.exterior.coords)[:-1]
        return []

    # 최대 면적 polygon 선택
    largest = max(polys, key=lambda p: p.area)
    coords = list(largest.exterior.coords)[:-1]  # 마지막 중복점 제거
    print(f"[PDFParser] polygon: {len(coords)} pts, area={largest.area:.0f} pt²")
    return coords


def _extract_inner_walls(
    segments: list[tuple[tuple[float, float], tuple[float, float]]],
    floor_polygon: list[tuple[float, float]],
) -> list[DetectedLineSegment]:
    """외벽(floor_polygon 변) 제외한 내부 선분 추출."""
    from shapely.geometry import LineString, Polygon

    if len(floor_polygon) < 3:
        return []

    fp = Polygon(floor_polygon)
    exterior_coords = list(fp.exterior.coords)
    walls = []

    for (x0, y0), (x1, y1) in segments:
        seg = LineString([(x0, y0), (x1, y1)])
        if seg.length < 10:  # 짧은 선분 무시
            continue

        # 외벽 변과의 거리가 5pt 미만이면 외벽으로 간주
        is_exterior = False
        for i in range(len(exterior_coords) - 1):
            edge = LineString([exterior_coords[i], exterior_coords[i + 1]])
            if seg.distance(edge) < 5:
                is_exterior = True
                break

        if not is_exterior and fp.contains(seg.centroid):
            walls.append(DetectedLineSegment(
                start_px=(x0, y0),
                end_px=(x1, y1),
                confidence="high",
            ))

    return walls


# ── 치수/스케일 ──────────────────────────────────────────────────────────────

def _extract_dimension_texts(
    page,
    page_height: float,
) -> list[dict]:
    """페이지에서 숫자 텍스트 추출 → 위치 + mm 값."""
    results = []
    words = page.extract_words() or []

    for w in words:
        text = w.get("text", "")
        m = _DIM_PATTERN.match(text.strip())
        if m:
            val = float(m.group(1))
            if 100 <= val <= 50000:  # 합리적 mm 범위
                x = float(w["x0"])
                y = page_height - float(w["top"])
                results.append({"value_mm": val, "x": x, "y": y, "text": text})

    return results


def _calc_scale(
    dim_texts: list[dict],
    segments: list[tuple[tuple[float, float], tuple[float, float]]],
) -> Optional[float]:
    """
    치수 텍스트와 가장 가까운 선분을 매칭 → mm/pt 스케일 계산.
    가장 긴 선분 매칭을 우선.
    """
    if not dim_texts or not segments:
        return None

    candidates = []

    for dim in dim_texts:
        dx, dy = dim["x"], dim["y"]
        mm_val = dim["value_mm"]

        # 텍스트 위치에 가장 가까운 선분 찾기
        best_seg = None
        best_dist = float("inf")

        for (x0, y0), (x1, y1) in segments:
            # 선분 중점과 텍스트 거리
            mx, my = (x0 + x1) / 2, (y0 + y1) / 2
            d = math.hypot(mx - dx, my - dy)
            if d < best_dist:
                best_dist = d
                best_seg = ((x0, y0), (x1, y1))

        if best_seg and best_dist < 100:  # 100pt 이내만
            (x0, y0), (x1, y1) = best_seg
            pt_len = math.hypot(x1 - x0, y1 - y0)
            if pt_len > 5:
                candidates.append((pt_len, mm_val / pt_len))

    if not candidates:
        return None

    # 가장 긴 pt 선분의 스케일 채택
    candidates.sort(key=lambda x: x[0], reverse=True)
    scale = candidates[0][1]
    print(f"[PDFParser] scale: {scale:.4f} mm/pt (from {len(candidates)} candidates)")
    return scale


def _find_entrance(
    dim_texts: list[dict],
    floor_polygon: list[tuple[float, float]],
) -> Optional[DetectedPoint]:
    """텍스트에서 입구 키워드 탐색 → 위치 반환."""
    for dim in dim_texts:
        text_lower = dim.get("text", "").lower()
        if any(kw in text_lower for kw in _ENTRANCE_KEYWORDS):
            return DetectedPoint(x_px=dim["x"], y_px=dim["y"], confidence="medium")

    # 텍스트에서 못 찾으면 floor polygon 하단 중앙을 기본 입구로
    if floor_polygon:
        xs = [p[0] for p in floor_polygon]
        ys = [p[1] for p in floor_polygon]
        return DetectedPoint(
            x_px=(min(xs) + max(xs)) / 2,
            y_px=min(ys),
            confidence="low",
        )

    return None


# ── 헬퍼 ──────────────────────────────────────────────────────────────────────

def _polygon_width(pts: list[tuple[float, float]]) -> float:
    xs = [p[0] for p in pts]
    return max(xs) - min(xs)


def _polygon_height(pts: list[tuple[float, float]]) -> float:
    ys = [p[1] for p in pts]
    return max(ys) - min(ys)


def _rasterize_pdf(pdf_bytes: bytes, dpi: int = 150) -> bytes:
    """스캔 PDF fallback — 첫 페이지를 PNG로 래스터화."""
    import fitz

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    page = doc[0]
    mat = fitz.Matrix(dpi / 72, dpi / 72)
    pix = page.get_pixmap(matrix=mat, alpha=False)
    return pix.tobytes("png")
