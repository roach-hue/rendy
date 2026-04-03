import base64
import json
import re

import anthropic
import cv2
import numpy as np

from app.parsers.base import FloorPlanParser
from app.schemas.drawings import (
    DetectedLineSegment,
    DetectedPoint,
    DetectedPolygon,
    ParsedDrawings,
    ParsedFloorPlan,
    ParsedSection,
)

def _get_client() -> anthropic.Anthropic:
    return anthropic.Anthropic()  # 호출 시점에 env에서 API key 읽음

VISION_PROMPT = """당신은 건축 평면도 분석 전문가입니다.
아래 도면 이미지에서 항목들을 감지하여 아래 JSON 형식만 출력하세요. 다른 텍스트 금지.

{
  "floor_polygon_px": [[x1,y1],[x2,y2],[x3,y3],[x4,y4]],
  "dimensions": [
    {"value_mm": 6000, "start_px": [100, 50], "end_px": [700, 50]}
  ],
  "entrance": {"x_px": 0, "y_px": 0, "confidence": "high"},
  "sprinklers": [{"x_px": 0, "y_px": 0, "confidence": "high"}],
  "fire_hydrant": [{"x_px": 0, "y_px": 0, "confidence": "high"}],
  "electrical_panel": [{"x_px": 0, "y_px": 0, "confidence": "high"}],
  "inner_walls": [{"start_px": [0, 0], "end_px": [0, 0], "confidence": "high"}],
  "inaccessible_rooms": [{"polygon_px": [[0,0],[0,0],[0,0]], "confidence": "medium"}]
}

규칙:
- floor_polygon_px: 건물의 가장 바깥쪽 외벽(외곽선)의 꼭짓점 픽셀 좌표 배열. 건물 전체를 둘러싸는 가장 큰 닫힌 사각형/다각형. 내부 구획벽이나 존(zone) 경계가 아니라 건물 외벽. 치수선·타이틀 블록·여백은 제외. 최소 4개 이상의 꼭짓점.
- dimensions: 치수선 양 끝점 픽셀 좌표 + 표기된 수치(mm). cm면 ×10, m면 ×1000. 없으면 [].
- entrance: 문/출입구 위치 1개. 없으면 null.
- sprinklers / fire_hydrant / electrical_panel: 해당 설비 좌표 배열. 없으면 [].
- inner_walls: 외벽 제외, 내부 구획 벽만. 없으면 [].
- inaccessible_rooms: 화장실·창고 등 폐쇄 공간 폴리곤. 없으면 [].
- confidence: 확실하면 "high", 추정이면 "medium", 불확실하면 "low".
- 확실하지 않은 항목은 confidence "low"로 표기. 추측해서 "high" 금지.
- 도면 바깥 타이틀 블록·범례 영역의 심볼은 설비로 감지하지 말 것.
"""


class ImageParser(FloorPlanParser):
    """
    이미지 도면(PNG/JPG 등) 파서.
    - OpenCV: 바닥 polygon 추출 + OCR 스케일 계산
    - Claude Vision: 설비 + 내부 벽 1회 호출 감지
    """

    async def parse(self) -> ParsedDrawings:
        img_array = np.frombuffer(self.floor_bytes, dtype=np.uint8)
        img = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
        if img is None:
            raise ValueError("이미지 디코딩 실패 — 파일 손상 또는 지원하지 않는 형식")

        scale_mm_per_px, vision_result = _call_vision_combined(self.floor_bytes)

        # OpenCV로 건물 위치(중심+범위), Vision으로 치수(mm) — 결합
        opencv_polygon = _extract_floor_polygon(img)
        det_w, det_h = _extract_building_dims(vision_result.get("dimensions", []))

        if det_w and det_h and len(opencv_polygon) >= 3:
            # OpenCV polygon 중심 + Vision 치수로 정확한 사각형 구성
            floor_polygon_px = _combine_opencv_vision(opencv_polygon, det_w, det_h, scale_mm_per_px)
            print(f"[ImageParser] floor polygon: OpenCV position + Vision dims ({det_w}x{det_h}mm)")
        else:
            floor_polygon_px = opencv_polygon
            print(f"[ImageParser] floor polygon: OpenCV only ({len(floor_polygon_px)} points)")

        floor_plan = ParsedFloorPlan(
            floor_polygon_px=floor_polygon_px,
            scale_mm_per_px=scale_mm_per_px,
            scale_confirmed=(scale_mm_per_px != 10.0),
            detected_width_mm=det_w,
            detected_height_mm=det_h,
            entrance=_to_point(vision_result.get("entrance")),
            sprinklers=[_to_point(p) for p in vision_result.get("sprinklers", []) if p],
            fire_hydrant=[_to_point(p) for p in vision_result.get("fire_hydrant", []) if p],
            electrical_panel=[_to_point(p) for p in vision_result.get("electrical_panel", []) if p],
            inner_walls=[_to_segment(s) for s in vision_result.get("inner_walls", []) if s],
            inaccessible_rooms=[_to_polygon(r) for r in vision_result.get("inaccessible_rooms", []) if r],
        )

        section = None
        if self.section_bytes:
            section = _parse_section_image(self.section_bytes)

        return ParsedDrawings(floor_plan=floor_plan, section=section)


# ── 내부 헬퍼 ──────────────────────────────────────────────────────────────

def _combine_opencv_vision(
    opencv_polygon: list[tuple[float, float]],
    width_mm: float,
    height_mm: float,
    scale: float,
) -> list[tuple[float, float]]:
    """
    OpenCV polygon의 중심 위치 + Vision 치수(mm)로 건물 사각형 구성.
    - OpenCV: 건물이 이미지 어디에 있는지 (위치) → 신뢰
    - Vision: 건물이 몇 mm인지 (치수) → 신뢰
    - Vision pixel 좌표 → 불신
    """
    xs = [p[0] for p in opencv_polygon]
    ys = [p[1] for p in opencv_polygon]
    cx = (min(xs) + max(xs)) / 2
    cy = (min(ys) + max(ys)) / 2

    half_w_px = (width_mm / scale) / 2
    half_h_px = (height_mm / scale) / 2

    result = [
        (cx - half_w_px, cy - half_h_px),
        (cx + half_w_px, cy - half_h_px),
        (cx + half_w_px, cy + half_h_px),
        (cx - half_w_px, cy + half_h_px),
    ]
    print(f"[ImageParser] combined: center=({cx:.0f},{cy:.0f}), "
          f"size={half_w_px*2:.0f}x{half_h_px*2:.0f}px")
    return result


def _extract_building_dims(dims: list[dict]) -> tuple[float | None, float | None]:
    """치수선에서 가장 큰 가로 value_mm, 가장 큰 세로 value_mm 추출."""
    max_h_val = None  # 가로 (horizontal)
    max_v_val = None  # 세로 (vertical)

    for d in dims:
        try:
            sx, sy = d["start_px"]
            ex, ey = d["end_px"]
            val = float(d.get("value_mm", 0))
            if val <= 0:
                continue
            dx = abs(ex - sx)
            dy = abs(ey - sy)
            if dx > dy:  # 가로 치수
                if max_h_val is None or val > max_h_val:
                    max_h_val = val
            else:  # 세로 치수
                if max_v_val is None or val > max_v_val:
                    max_v_val = val
        except (KeyError, TypeError, ValueError):
            continue

    print(f"[ImageParser] detected building dims: width={max_h_val}mm, height={max_v_val}mm")
    return max_h_val, max_v_val


def _polygon_from_dimensions(dims: list[dict]) -> list[tuple[float, float]] | None:
    """
    가장 긴 가로 치수선 + 가장 긴 세로 치수선의 끝점으로 건물 외벽 사각형 구성.
    내부 치수선(900, 1200 등)은 무시 — 가장 큰 value_mm 기준.
    """
    if len(dims) < 2:
        print(f"[ImageParser] dimensions too few ({len(dims)}), skip")
        return None

    horizontal = []  # 가로 치수선 (dx > dy)
    vertical = []    # 세로 치수선 (dy > dx)

    for d in dims:
        try:
            sx, sy = d["start_px"]
            ex, ey = d["end_px"]
            dx = abs(ex - sx)
            dy = abs(ey - sy)
            val = d.get("value_mm", 0)
            if dx > dy:
                horizontal.append({"sx": sx, "sy": sy, "ex": ex, "ey": ey, "val": val})
            else:
                vertical.append({"sx": sx, "sy": sy, "ex": ex, "ey": ey, "val": val})
        except (KeyError, TypeError):
            continue

    if not horizontal or not vertical:
        print(f"[ImageParser] need both h/v dims: h={len(horizontal)}, v={len(vertical)}")
        return None

    # 가장 큰 value_mm = 건물 전체 치수
    h_dim = max(horizontal, key=lambda d: d["val"])
    v_dim = max(vertical, key=lambda d: d["val"])

    left   = min(h_dim["sx"], h_dim["ex"])
    right  = max(h_dim["sx"], h_dim["ex"])
    top    = min(v_dim["sy"], v_dim["ey"])
    bottom = max(v_dim["sy"], v_dim["ey"])

    print(f"[ImageParser] building from dims: h={h_dim['val']}mm ({left}-{right}px), v={v_dim['val']}mm ({top}-{bottom}px)")

    if (right - left) < 50 or (bottom - top) < 50:
        print(f"[ImageParser] dimension bbox too small")
        return None

    return [
        (float(left), float(top)),
        (float(right), float(top)),
        (float(right), float(bottom)),
        (float(left), float(bottom)),
    ]


def _extract_floor_polygon(img: np.ndarray) -> list[tuple[float, float]]:
    """OpenCV로 건물 외벽 윤곽선 추출. 이미지 전체 테두리(여백)는 제외."""
    h, w = img.shape[:2]
    image_area = h * w
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blur, 50, 150)
    dilated = cv2.dilate(edges, np.ones((3, 3), np.uint8), iterations=2)

    contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        raise ValueError("바닥 polygon 추출 실패 — 윤곽선 미감지")

    # 면적 내림차순 정렬
    contours_sorted = sorted(contours, key=cv2.contourArea, reverse=True)

    for contour in contours_sorted:
        area = cv2.contourArea(contour)
        # 이미지 전체 면적의 85% 이상이면 이미지 테두리 → 스킵
        if area > image_area * 0.85:
            print(f"[ImageParser] skipping contour: area={area} ({area/image_area*100:.0f}% of image)")
            continue
        # 이미지 면적의 5% 미만이면 노이즈 → 스킵
        if area < image_area * 0.05:
            print(f"[ImageParser] skipping small contour: area={area}")
            continue
        epsilon = 0.01 * cv2.arcLength(contour, True)
        approx = cv2.approxPolyDP(contour, epsilon, True)
        result = [(float(pt[0][0]), float(pt[0][1])) for pt in approx]
        print(f"[ImageParser] floor polygon: {len(result)} points, area={area} ({area/image_area*100:.0f}% of image)")
        return result

    # fallback: 가장 큰 윤곽선 사용
    largest = contours_sorted[0]
    epsilon = 0.01 * cv2.arcLength(largest, True)
    approx = cv2.approxPolyDP(largest, epsilon, True)
    print(f"[ImageParser] fallback: using largest contour")
    return [(float(pt[0][0]), float(pt[0][1])) for pt in approx]




def _resize_for_vision(image_bytes: bytes, max_bytes: int = 4_500_000) -> bytes:
    """Vision API 5MB 제한 대응 — JPEG 리사이즈. 원본이 작으면 그대로 반환."""
    if len(image_bytes) <= max_bytes:
        print(f"[ImageParser] image size OK: {len(image_bytes)} bytes")
        return image_bytes
    img = cv2.imdecode(np.frombuffer(image_bytes, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        return image_bytes
    h, w = img.shape[:2]
    # 축소 비율 계산 (면적 비례)
    ratio = (max_bytes / len(image_bytes)) ** 0.5
    new_w, new_h = int(w * ratio), int(h * ratio)
    resized = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_AREA)
    _, buf = cv2.imencode(".jpg", resized, [cv2.IMWRITE_JPEG_QUALITY, 85])
    result = buf.tobytes()
    print(f"[ImageParser] resized {w}x{h} → {new_w}x{new_h}, {len(image_bytes)} → {len(result)} bytes")
    return result


def _call_vision_combined(image_bytes: bytes) -> tuple[float, dict]:
    """
    Claude Vision 1회 호출로 치수선(scale) + 설비 + 내부 벽 동시 감지.
    반환: (scale_mm_per_px, detection_dict)
    """
    vision_bytes = _resize_for_vision(image_bytes)
    media_type = "image/jpeg" if vision_bytes[:2] == b'\xff\xd8' else "image/png"
    b64 = base64.standard_b64encode(vision_bytes).decode()

    response = _get_client().messages.create(
        model="claude-sonnet-4-5",
        max_tokens=2048,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": b64}},
                {"type": "text", "text": VISION_PROMPT},
            ],
        }],
    )

    raw = response.content[0].text.strip()
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        raise ValueError(f"Vision 응답 파싱 실패: {raw[:200]}")

    json_str = match.group()
    data = _parse_json_lenient(json_str)
    scale = _scale_from_dimensions(data.get("dimensions", []))
    return scale, data


def _parse_json_lenient(raw: str) -> dict:
    """
    Vision LLM 응답의 malformed JSON 복구 후 파싱.
    - 작은따옴표 → 큰따옴표
    - trailing comma 제거
    - // 주석 제거
    """
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    fixed = raw
    # // 한줄 주석 제거
    fixed = re.sub(r'//[^\n]*', '', fixed)
    # 작은따옴표 → 큰따옴표 (문자열 내부 apostrophe는 드문 케이스)
    fixed = fixed.replace("'", '"')
    # trailing comma: ,\s*} 또는 ,\s*]
    fixed = re.sub(r',\s*([}\]])', r'\1', fixed)

    try:
        return json.loads(fixed)
    except json.JSONDecodeError as e:
        raise ValueError(f"Vision JSON 복구 실패: {e}\n원본: {raw[:300]}")


def _scale_from_dimensions(dims: list[dict]) -> float:
    """
    치수선 목록에서 scale_mm_per_px 계산.
    전략: 픽셀 길이가 가장 긴 치수선을 사용 (전체 도면 치수일 가능성 가장 높음).
    짧은 내부 치수선은 픽셀 오차 영향이 크므로 제외.
    실패 시 10.0 fallback.
    """
    candidates = []
    for d in dims:
        try:
            sx, sy = d["start_px"]
            ex, ey = d["end_px"]
            px_len = ((ex - sx) ** 2 + (ey - sy) ** 2) ** 0.5
            if px_len > 10:  # 10px 미만 선분은 노이즈로 제외
                candidates.append((px_len, d["value_mm"] / px_len))
        except (KeyError, TypeError, ZeroDivisionError):
            continue

    if not candidates:
        return 10.0

    # 픽셀 길이가 가장 긴 치수선 선택 (전체 도면 치수)
    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1]


def _parse_section_image(section_bytes: bytes) -> ParsedSection:
    """단면도 이미지에서 ceiling_height_mm 추출 (Vision)."""
    b64 = base64.standard_b64encode(section_bytes).decode()
    prompt = (
        "이 단면도에서 천장 높이(ceiling height)를 mm 단위로 추출하세요. "
        "숫자만 반환하세요. 예: 2800\n"
        "없으면 null을 반환하세요."
    )
    response = _get_client().messages.create(
        model="claude-sonnet-4-5",
        max_tokens=64,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": b64}},
                    {"type": "text", "text": prompt},
                ],
            }
        ],
    )
    raw = response.content[0].text.strip()
    try:
        val = float(raw) if raw.lower() != "null" else None
    except ValueError:
        val = None
    return ParsedSection(ceiling_height_mm=val)


# ── 스키마 변환 헬퍼 ───────────────────────────────────────────────────────

def _to_point(d: dict | None) -> DetectedPoint | None:
    if not d:
        return None
    return DetectedPoint(x_px=d["x_px"], y_px=d["y_px"], confidence=d.get("confidence", "low"))


def _to_segment(d: dict) -> DetectedLineSegment:
    return DetectedLineSegment(
        start_px=tuple(d["start_px"]),
        end_px=tuple(d["end_px"]),
        confidence=d.get("confidence", "low"),
    )


def _to_polygon(d: dict) -> DetectedPolygon:
    return DetectedPolygon(
        polygon_px=[tuple(p) for p in d["polygon_px"]],
        confidence=d.get("confidence", "low"),
    )
