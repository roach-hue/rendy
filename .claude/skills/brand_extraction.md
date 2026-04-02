---
name: 브랜드 수치 추출 스킬
description: Agent 1이 브랜드 메뉴얼 PDF에서 수치/규정을 추출하는 프레임워크
---

# 브랜드 수치 추출 스킬 (Brand Extraction Skill)

## 목적
브랜드 메뉴얼 PDF에서 이격 수치, 배치 규정, 관계 제약을 추출하여 `space_data["brand"]`에 저장.

---

## 추출 대상 (5개)

| 필드 | 설명 | 예시 |
|------|------|------|
| `clearspace_mm` | 이격/여백 수치 | 1500mm |
| `character_orientation` | 배치 방향 규정 | "정면 향하도록" |
| `prohibited_material` | 금지 소재 | "메탈 소재 금지" |
| `logo_clearspace_mm` | 로고 여백 | 500mm |
| `relationships` | 관계 제약 (자연어 그대로) | "라이언과 춘식이를 떨어뜨릴 것" |

---

## 처리 분기

### 텍스트 PDF — Regex + LLM 라벨링 hybrid

> ⚠️ LLM이 수치를 직접 추출하는 것 금지. Regex가 숫자/단위를 기계 추출하고 LLM은 라벨링만 수행.

```
Step 1: PDF에서 텍스트 추출 (pdfplumber 등)
Step 2: Python Regex로 숫자+단위 패턴 기계 추출
        패턴 예: r'(\d+)\s*(mm|cm|m)\b'
Step 3: 추출된 (수치, 단위, 주변 문맥) 쌍을 LLM에 전달
Step 4: LLM은 "이 수치가 5개 필드 중 어디에 해당하는지" 라벨링만 수행
Step 5: Pydantic 검증 → space_data["brand"] 저장
```

**Regex hybrid 도입 이유** (architecture_decisions.md Issue 1):
- LLM이 400mm를 4000mm로 환각해도 값 범위(300~5000) validator 통과 가능
- Regex로 기계 추출하면 수치 자체의 정확도는 100% 보장
- LLM은 "이 숫자가 무슨 규정인지" 의미 판단에만 사용

### 이미지 PDF — Claude Vision

```
Step 1: PDF를 이미지로 변환
Step 2: Claude Vision에 이미지 + 추출 프롬프트 전달
Step 3: Vision 출력에서 수치/규정 파싱
Step 4: Pydantic 검증 → space_data["brand"] 저장
```

> 이미지 PDF는 Regex 적용 불가하므로 Vision 유지. 단, Vision 환각 위험은 사용자 확인 UI에서 보완.

---

## 필드 래핑 규칙

모든 브랜드 필드는 반드시 아래 형식으로 래핑:

```python
{
    "value": 1500,              # 실제 값
    "confidence": "high",       # high | medium | low
    "source": "manual"          # manual | default | user_corrected
}
```

### confidence 기준
```
high   — Regex 기계 추출 또는 사용자 직접 입력
medium — Vision 추출 (환각 가능성)
low    — 문맥 추론 (주변 텍스트에서 간접 추정)
```

### null 처리
```
추출 실패 → null 저장 (추측 금지)
→ DEFAULTS dict로 merge
→ source: "default" 기록
→ 리포트에 "기본값 사용" 명시
```

---

## Pydantic 검증

```python
@validator("clearspace_mm")
def check_range(cls, v):
    if v < 300 or v > 5000:
        raise ValueError(f"비정상 범위: {v}mm")
    return v
```

- 검증 실패 → 재시도 최대 3회 (Circuit Breaker)
- 3회 실패 → 파이프라인 중단

---

## relationships 처리

- 자연어 그대로 보존 — 수치 변환하지 않음
- 예: `"라이언과 춘식이를 떨어뜨릴 것"` → 그대로 저장
- Agent 3 프롬프트에 전달 시 자연어 그대로 주입
- 검증은 배치 완료 후 Shapely.distance < clearspace_mm 비교로 수행 (Issue 14 — zone_label 비교 기각)

---

## 출력 형식

```python
space_data["brand"] = {
    "clearspace_mm": {"value": 1500, "confidence": "high", "source": "manual"},
    "character_orientation": {"value": "정면 향하도록", "confidence": "high", "source": "manual"},
    "prohibited_material": {"value": "메탈 소재", "confidence": "medium", "source": "manual"},
    "logo_clearspace_mm": {"value": 500, "confidence": "high", "source": "manual"},
    "relationships": [
        {"rule": "라이언과 춘식이를 떨어뜨릴 것", "confidence": "high"}
    ]
}
```

---

## 주의사항

- Regex 추출 결과와 LLM 라벨링 결과를 혼동하지 않을 것
- LLM이 "이 수치는 1500mm가 아니라 15000mm일 것 같다" 식으로 수치를 수정하는 것 금지
- 이미지 PDF에서 Vision 추출 시 confidence를 "medium"으로 설정
- 사용자 확인 UI에서 수정된 값은 source를 "user_corrected"로 변경
