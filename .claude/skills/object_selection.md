---
name: 오브젝트 선별 스킬
description: space_data와 Supabase furniture_standards를 비교하여 배치 가능한 오브젝트 목록을 생성하는 규칙
---

# 오브젝트 선별 스킬 (Object Selection Skill)

## 목적
space_data의 공간 제약과 Supabase `furniture_standards` 테이블을 대조하여, 실제 배치 가능한 `eligible_objects` 리스트를 생성.

> ⚠️ 이 모듈은 순수 코드 — LLM 개입 없음

---

## 처리 순서

```
Step 1: Supabase furniture_standards 테이블 조회
  → 해당 브랜드/카테고리의 오브젝트 목록 로드
  → 각 오브젝트의 bbox (width_mm, depth_mm, height_mm) 포함

Step 2: 공간 제약 필터링
  → space_data["floor"]["max_object_w_mm"]보다 큰 오브젝트 제외
  → space_data["floor"]["usable_area_sqm"]에 비해 과도하게 큰 오브젝트 제외

Step 3: 브랜드 제약 필터링
  → space_data["brand"]["prohibited_material"]["value"] 해당 오브젝트 제외
    (brand 필드는 {"value":..., "confidence":..., "source":...} 래핑 구조)

Step 4: eligible_objects 생성
  → bbox 포함한 최종 목록
```

---

## eligible_objects 출력 형식

```python
eligible_objects = [
    {
        "object_type": "character_ryan",
        "width_mm": 800,
        "depth_mm": 800,
        "height_mm": 2000,
        "category": "character",
        "source": "furniture_standards",
        "can_join": False,         # 연속 배치 허용 여부 (Issue 20)
        "overlap_margin_mm": 0     # 파고드는 마진 — can_join=True 시 사용
    },
    {
        "object_type": "shelf_3tier",
        "width_mm": 1200,
        "depth_mm": 400,
        "height_mm": 1200,
        "category": "shelf",
        "source": "furniture_standards"
    }
]
```

---

## 제외 기준

| 제외 사유 | 기준 |
|-----------|------|
| 공간 미달 | 오브젝트 width > max_object_w_mm |
| 면적 초과 | 오브젝트 바닥 면적 합 > usable_area_sqm의 일정 비율 |
| 브랜드 금지 | prohibited_material에 해당 |

---

## 주의사항

- eligible_objects는 "배치 가능 후보"이지 "배치 확정"이 아님
- 실제 배치 가부는 코드 순회 루프에서 Shapely 검증으로 최종 판정
- Supabase 조회 실패 시 에러 로깅 후 파이프라인 중단 (빈 목록으로 진행 금지)
