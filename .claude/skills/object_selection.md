---
name: 오브젝트 선별 스킬
description: space_data와 Supabase furniture_standards를 비교하여 배치 가능한 오브젝트 목록을 생성하는 규칙
---

# 오브젝트 선별 (Object Selection)

> 순수 코드 모듈 — LLM 개입 없음

---

## 파이프라인 위치

```
Agent 2 후반부 완료 (space_data 확정)
    ↓
[오브젝트 선별 모듈]   ← 여기
    ↓
Agent 3 입력: eligible_objects 목록 전달
```

---

## 입력

| 항목 | 타입 | 출처 |
|------|------|------|
| `space_data["floor"]["max_object_w_mm"]` | float | Agent 2 후반부 계산 |
| `space_data["floor"]["usable_area_sqm"]` | float | Agent 2 후반부 계산 |
| `space_data["floor"]["ceiling_height_mm"]["value"]` | float | 단면도 추출 또는 DEFAULTS 3000mm |
| `space_data["brand"]["prohibited_material"]["value"]` | str \| None | Agent 1 추출 또는 None |
| `brand_id` | str | 파이프라인 파라미터 |

---

## 처리 순서

### Step 1: Supabase 조회

```python
# furniture_standards 테이블 쿼리
rows = supabase.table("furniture_standards") \
    .select("object_type, width_mm, depth_mm, height_mm, category, can_join, overlap_margin_mm") \
    .eq("brand_id", brand_id) \
    .execute().data

# brand_id 미매칭 시 category="generic" fallback 조회
# 조회 실패(네트워크 오류 등) → 에러 로깅 후 파이프라인 중단 (빈 목록으로 계속 진행 금지)
```

### Step 2: 공간 제약 필터

```python
max_w = space_data["floor"]["max_object_w_mm"]
ceiling_h = space_data["floor"]["ceiling_height_mm"]["value"]

for obj in rows:
    # 필터 1: 너비 초과
    if obj["width_mm"] > max_w:
        continue

    # 필터 2: 천장 높이 초과 (Issue 22)
    if obj["height_mm"] > ceiling_h:
        continue

    eligible.append(obj)
```

`usable_area_sqm` 기반 면적 총량 제한은 **미결** (테스트 후 비율 수치 결정). 현재는 미적용.

### Step 3: 브랜드 금지 소재 필터

```python
prohibited = space_data["brand"].get("prohibited_material", {}).get("value")

if prohibited:
    eligible = [obj for obj in eligible if prohibited not in obj.get("material", "")]
```

`prohibited_material`이 None이면 스킵.

### Step 4: eligible_objects 반환

```python
return eligible  # 빈 목록이면 파이프라인 중단 (배치할 오브젝트 없음)
```

---

## eligible_objects 출력 형식

```python
eligible_objects = [
    {
        "object_type": "character_ryan",   # Placement.object_type과 동일 키
        "width_mm": 800,
        "depth_mm": 800,
        "height_mm": 2000,
        "category": "character",
        "source": "furniture_standards",
        "can_join": False,           # True면 join_with 쌍 배치 허용 (Issue 20)
        "overlap_margin_mm": 0       # can_join=True 시 겹침 허용 마진 (mm)
    },
    {
        "object_type": "shelf_3tier",
        "width_mm": 1200,
        "depth_mm": 400,
        "height_mm": 1200,
        "category": "shelf",
        "source": "furniture_standards",
        "can_join": True,
        "overlap_margin_mm": 50
    }
]
```

**Agent 3에 전달하는 것**: `object_type` + `category`만. 수치(width_mm 등)는 전달 금지 — LLM이 mm 출력 못하도록 차단.
**코드가 직접 조회하는 것**: calculate_position에서 `object_type`을 키로 `eligible_objects` 리스트에서 bbox 직접 조회.

---

## 제외 기준 요약

| 제외 사유 | 판단 기준 | 데이터 출처 |
|-----------|-----------|-------------|
| 너비 초과 | `width_mm > max_object_w_mm` | Agent 2 후반부 |
| 천장 높이 초과 | `height_mm > ceiling_height_mm["value"]` | 단면도 / DEFAULTS |
| 브랜드 금지 소재 | `prohibited_material` 매칭 | Agent 1 |

---

## 주의

- `eligible_objects`는 배치 가능 후보 목록. 확정이 아님
- 최종 배치 가부는 코드 순회 루프의 Shapely 충돌 + NetworkX 통로 검증으로 결정
