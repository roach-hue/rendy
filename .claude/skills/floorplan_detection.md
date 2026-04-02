---
name: 도면 감지 스킬
description: Agent 2 전반부가 도면 파일에서 바닥 polygon, 입구, 설비 위치를 자동 감지하는 프레임워크
---

# 도면 감지 스킬 (Floorplan Detection Skill)

## 목적
도면 파일에서 바닥 polygon, 스케일, 입구/설비 위치를 자동 감지하여 `auto_detected` dict를 생성.

---

## 파서 어댑터 패턴

> 파일 형식별 파싱은 FloorPlanParser 추상 클래스를 상속한 어댑터에서만 처리.
> Agent 2가 파일 형식을 직접 분기하는 것 금지. (claude.md 참조)

```
FloorPlanParser (추상)
  └── DWGParser    ← DXF via ezdxf (스케일·치수 직접 추출)
  └── PDFParser    ← 래스터화 후 Vision 파이프라인
  └── ImageParser  ← OpenCV + Claude Vision
```

모든 파서는 `ParsedFloorPlan` 공통 스키마로 정규화 후 후속 처리에 전달.

---

## 처리 순서

### Step 1: OpenCV — 바닥 polygon 추출 (픽셀)

```
1. 도면 이미지 로드
2. 그레이스케일 변환 + 노이즈 제거
3. 외곽선 감지 (Canny edge detection)
4. 최대 면적 윤곽선 → 바닥 polygon (픽셀 좌표)
5. 결과: floor_polygon_px
```

### Step 2: OCR — 치수선 → 스케일 계산

```
1. OCR로 도면 내 텍스트 추출
2. 치수선 패턴 감지 (예: "6000", "4000" + mm/cm 단위)
3. 치수선의 픽셀 길이와 실제 길이 비교
4. scale_mm_per_px 계산
5. 치수선이 여러 개면 평균값 사용, 편차 큰 것은 이상치 제외
```

### Step 3: Claude Vision — 설비 + 내부 벽 감지

```
1. 도면 이미지를 Claude Vision에 전달
2. 한 번의 호출로 아래 6가지 동시 감지:
   - 입구 (entrance)
   - 스프링클러 (sprinklers)
   - 소화전 (fire_hydrant)
   - 분전반 (electrical_panel)
   - 내부 벽 (inner_walls) — 바닥 외벽과 구분되는 내부 구획 벽
   - 배치 불가 영역 (inaccessible_rooms) — 화장실, 창고 등 폐쇄된 방
3. 각 항목에 confidence 부여
4. 미감지 항목은 빈 배열 반환
```

> ⚠️ Vision 호출은 1회로 제한 — 항목별 개별 호출 금지 (API 비용 최적화)

#### Vision 프롬프트 가이드

```
역할: 건축 도면 분석 전문가
입력: 도면 이미지
요청: 아래 항목의 위치를 픽셀 좌표로 반환

1. 입구 (문, 출입구) — 좌표 1개
2. 스프링클러 — 좌표 배열
3. 소화전 — 좌표 배열
4. 분전반 — 좌표 배열
5. 내부 벽 — 선분 배열 (시작점/끝점 픽셀 좌표 쌍)
6. 배치 불가 영역 — 폴리곤 배열 (화장실, 창고 등 폐쇄 공간)

각 항목에 confidence (high/medium/low) 부여.
감지 못한 항목은 빈 배열로 반환.
추측하지 말 것 — 확실하지 않으면 confidence를 low로.
```

---

## 출력 형식

```python
auto_detected = {
    "floor_polygon_px": [(0,0), (600,0), (600,400), (0,400)],
    "scale_mm_per_px": 10.0,
    "entrance": {"x_px": 0, "y_px": 100, "confidence": "high"},
    "sprinklers": [
        {"x_px": 150, "y_px": 200, "confidence": "high"},
        {"x_px": 400, "y_px": 300, "confidence": "medium"}
    ],
    "fire_hydrant": [],
    "electrical_panel": [],
    "inner_walls": [
        {"start_px": (100, 0), "end_px": (100, 200), "confidence": "high"}
    ],
    "inaccessible_rooms": [
        {"polygon_px": [(500,300),(600,300),(600,400),(500,400)], "confidence": "medium"}
    ]
}
```

> 이 출력은 **임시** — 사용자 마킹 UI에서 확인/수정 후에만 Agent 2 후반부로 전달

---

## 에러 핸들링

```
OpenCV polygon 추출 실패:
  → 사용자에게 수동 마킹 요청 (도면 품질 문제일 가능성)

OCR 치수선 미감지:
  → 사용자에게 실제 치수 직접 입력 요청
  → scale_mm_per_px를 수동 계산

Vision 호출 실패:
  → 재시도 1회 → 실패 시 사용자 수동 마킹으로 전환

Vision confidence 전부 low:
  → 사용자에게 "자동 감지 신뢰도 낮음" 경고 + 수동 확인 강력 권장
```

---

## 주의사항

- auto_detected는 확정 데이터가 아님 — 사용자 확인 전까지 space_data에 저장하지 않음
- 파서가 어떤 형식이든 출력 스키마는 동일 (ParsedFloorPlan)
- Agent 프롬프트에 파일 형식명 직접 기재 금지
- DWG 주의: 상업용 서버 환경에서 ODA File Converter 무료 사용 불가. DXF 직접 업로드 유도 또는 APS API 연동 필요
