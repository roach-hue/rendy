"""
Agent 1 — 브랜드 수치 추출 (Regex + LLM 라벨링 hybrid)

처리 분기:
  텍스트 PDF → pdfplumber 텍스트 추출 → Regex 수치 기계 추출 → LLM 라벨링
  이미지 PDF → Claude Vision 전담

Circuit Breaker: Pydantic 검증 실패 시 최대 3회 재시도 → 초과 시 ValueError
"""
import base64
import json
import re

import anthropic
import pdfplumber

from app.core.defaults import DEFAULTS, merge_with_defaults
from app.schemas.brand import BrandData, BrandField, RelationshipRule

def _get_client() -> anthropic.Anthropic:
    return anthropic.Anthropic()  # 호출 시점에 env에서 API key 읽음

# 숫자 + 단위 패턴
_NUMBER_UNIT = re.compile(r"(\d+(?:\.\d+)?)\s*(mm|cm|m)\b", re.IGNORECASE)

# LLM 라벨링 프롬프트
_LABEL_PROMPT = """다음은 브랜드 메뉴얼에서 추출한 (수치, 단위, 문맥) 목록입니다.
각 항목이 아래 5개 필드 중 어디에 해당하는지 JSON으로 반환하세요.

필드 목록:
- clearspace_mm: 캐릭터/오브젝트 주변 이격 거리
- logo_clearspace_mm: 로고 주변 여백
- character_orientation: 배치 방향 규정 (수치 아님, 자연어)
- prohibited_material: 금지 소재 (수치 아님, 자연어)
- object_pair_rules: 특정 오브젝트 쌍 배치 규칙 (자연어)

입력:
{items}

출력 형식 (JSON만, 다른 텍스트 금지):
{{
  "clearspace_mm": {{"value": 1500, "confidence": "high"}},
  "logo_clearspace_mm": {{"value": 300, "confidence": "medium"}},
  "character_orientation": {{"value": "정면을 향하도록", "confidence": "high"}},
  "prohibited_material": {{"value": "메탈 소재", "confidence": "high"}},
  "object_pair_rules": [{{"rule": "라이언과 춘식이를 떨어뜨릴 것", "confidence": "high"}}]
}}

규칙:
- 해당 항목이 없으면 null.
- 수치는 mm로 통일 (cm×10, m×1000).
- LLM이 수치를 임의로 변경하는 것 금지 — 입력에서 읽은 값만 사용.
"""

_VISION_PROMPT = """이 브랜드 메뉴얼 이미지에서 다음 5개 항목을 추출하세요.

JSON만 반환하세요:
{{
  "clearspace_mm": {{"value": 1500, "confidence": "high"}},
  "logo_clearspace_mm": {{"value": null, "confidence": "low"}},
  "character_orientation": {{"value": "정면 향하도록", "confidence": "high"}},
  "prohibited_material": {{"value": null, "confidence": "low"}},
  "object_pair_rules": [{{"rule": "라이언과 춘식이를 떨어뜨릴 것", "confidence": "high"}}]
}}

- clearspace_mm: 캐릭터/오브젝트 주변 최소 이격 수치 (mm)
- logo_clearspace_mm: 로고 주변 여백 수치 (mm)
- character_orientation: 배치 방향 규정 (자연어)
- prohibited_material: 금지 소재 (자연어)
- object_pair_rules: 특정 오브젝트 쌍 규칙 (자연어 배열)
- 없으면 null. 수치는 mm 단위로 통일.
"""


def extract(pdf_bytes: bytes) -> dict:
    """
    브랜드 메뉴얼 PDF → space_data["brand"] dict 반환.
    Circuit Breaker: 최대 3회 재시도.
    """
    text = _extract_text(pdf_bytes)
    is_image_pdf = len(text.strip()) < 50

    last_error = None
    for attempt in range(3):
        try:
            if is_image_pdf:
                raw = _vision_extract(pdf_bytes)
            else:
                raw = _regex_llm_extract(text)

            brand_data = _validate(raw)
            result = _to_space_data_brand(brand_data)
            return merge_with_defaults({"brand": result})["brand"]

        except Exception as e:
            last_error = e
            continue

    raise ValueError(f"브랜드 추출 3회 실패: {last_error}")


# ── 텍스트 PDF 처리 ────────────────────────────────────────────────────────

def _extract_text(pdf_bytes: bytes) -> str:
    """pdfplumber로 텍스트 추출."""
    import io
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        return "\n".join(
            page.extract_text() or "" for page in pdf.pages
        )


def _regex_llm_extract(text: str) -> dict:
    """Regex로 수치 추출 → LLM 라벨링."""
    items = []
    for m in _NUMBER_UNIT.finditer(text):
        start = max(0, m.start() - 60)
        end   = min(len(text), m.end() + 60)
        context = text[start:end].replace("\n", " ").strip()
        unit = m.group(2).lower()
        val = float(m.group(1))
        # mm 단위 통일
        if unit == "cm":
            val *= 10
        elif unit == "m":
            val *= 1000
        items.append({"value_mm": val, "context": context})

    # 자연어 규정도 LLM에 함께 전달
    prompt = _LABEL_PROMPT.format(
        items=json.dumps(items, ensure_ascii=False, indent=2)
        + f"\n\n전체 텍스트 (참고용):\n{text[:3000]}"
    )

    response = _get_client().messages.create(
        model="claude-sonnet-4-5",
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = response.content[0].text.strip()
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        raise ValueError(f"LLM 라벨링 응답 파싱 실패: {raw[:200]}")
    return json.loads(match.group())


# ── 이미지 PDF 처리 ────────────────────────────────────────────────────────

def _vision_extract(pdf_bytes: bytes) -> dict:
    """이미지 PDF → Claude Vision으로 직접 추출."""
    import fitz
    import io
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    page = doc[0]
    pix = page.get_pixmap(matrix=fitz.Matrix(150/72, 150/72), alpha=False)
    img_bytes = pix.tobytes("png")
    b64 = base64.standard_b64encode(img_bytes).decode()

    response = _get_client().messages.create(
        model="claude-sonnet-4-5",
        max_tokens=1024,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": b64}},
                {"type": "text", "text": _VISION_PROMPT},
            ],
        }],
    )
    raw = response.content[0].text.strip()
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        raise ValueError(f"Vision 응답 파싱 실패: {raw[:200]}")
    return json.loads(match.group())


# ── 검증 + 변환 ───────────────────────────────────────────────────────────

def _validate(raw: dict) -> BrandData:
    """Pydantic으로 검증. 실패 시 ValueError (Circuit Breaker 카운트)."""
    def _field(key: str, source: str = "manual") -> BrandField | None:
        v = raw.get(key)
        if not v or v.get("value") is None:
            return None
        return BrandField(
            value=v["value"],
            confidence=v.get("confidence", "low"),
            source=source,
        )

    rules = [
        RelationshipRule(rule=r["rule"], confidence=r.get("confidence", "low"))
        for r in (raw.get("object_pair_rules") or [])
        if r and r.get("rule")
    ]

    return BrandData(
        clearspace_mm=_field("clearspace_mm"),
        character_orientation=_field("character_orientation"),
        prohibited_material=_field("prohibited_material"),
        logo_clearspace_mm=_field("logo_clearspace_mm"),
        object_pair_rules=rules,
    )


def _to_space_data_brand(bd: BrandData) -> dict:
    """BrandData → space_data["brand"] dict 형식 변환."""
    result: dict = {}
    for field_name in ("clearspace_mm", "character_orientation", "prohibited_material", "logo_clearspace_mm"):
        field_val = getattr(bd, field_name)
        result[field_name] = field_val.model_dump() if field_val else None
    result["object_pair_rules"] = [r.model_dump() for r in bd.object_pair_rules]
    return result
