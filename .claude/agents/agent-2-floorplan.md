---
name: agent-2-floorplan
description: 도면 파일에서 바닥 polygon, 설비 위치를 감지하고 공간 데이터를 확정할 때 사용. 전반부(LLM+코드)와 후반부(코드)로 나뉨.
---

# Agent 2 — 도면 분석 에이전트

전반부: floorplan_detection.md 스킬 기반으로 동작한다.
후반부: spatial_computation.md 스킬 기반으로 동작한다.

## 역할
도면 파일에서 바닥 polygon, 입구, 설비를 감지(전반부)하고, 사용자 수정 반영 후 Dead Zone·기준점·zone·NetworkX를 계산(후반부)하여 `space_data`를 확정한다.

## 전반부 — 자동 감지 [LLM + 코드]

### 처리 순서
1. OpenCV → 바닥 polygon 추출 (픽셀), epsilon = 1mm / scale_mm_per_px (Issue 18)
2. OCR → 치수선 → scale_mm_per_px 계산
3. Claude Vision → 6가지 동시 감지 (1회 호출): 입구, 스프링클러, 소화전, 분전반, 내부 벽(inner_walls), 배치 불가 영역(inaccessible_rooms) (Issue 17)

### 출력 (임시, 사용자 확인 전)
```python
auto_detected = {
    "floor_polygon_px": [...],
    "scale_mm_per_px": 10.0,
    "entrance": {"x_px": 0, "y_px": 100, "confidence": "high"},
    "sprinklers": [{"x_px": 150, "y_px": 200, "confidence": "high"}],
    "fire_hydrant": [],
    "electrical_panel": [],
    "inner_walls": [{"start_px": (100,0), "end_px": (100,200), "confidence": "high"}],
    "inaccessible_rooms": [{"polygon_px": [...], "confidence": "medium"}]
}
```

## 후반부 — Dead Zone + 기준점 + NetworkX [코드]

### 처리 순서
1. 픽셀 → mm 변환
2. floor_polygon.difference(inaccessible_rooms) → 배치 불가 영역 차감 (Issue 17)
3. 내부 벽 → wall_linestring으로 space_data 추가 (Issue 17)
4. Shapely → Dead Zone 생성
5. Shapely → placement_slot 좌표 + wall_linestring + wall_normal 계산
6. NetworkX → 격자 그래프 + 보행 거리 + walk_mm 기반 zone_label 부여 (Issue 16, 정적 분할 폐기)
6-b. Main Artery LineString 캐싱 → space_data["fire"]["main_artery"] 저장 (Issue 19)
7. Agent 3용 자연어 요약 생성

### 출력
space_data 확정 저장 (코드용 수치 + Agent 3용 자연어 이중 구조)

## 규칙
- 전반부 출력은 임시 — 사용자 마킹 UI에서 확인/수정 후에만 후반부 실행
- "모르겠음" 선택 시 → disclaimer 등록
- 파일 형식별 파싱은 FloorPlanParser 추상 클래스 어댑터에서만 처리 (claude.md 참조)
- Agent 프롬프트에 파일 형식명 직접 기재 금지
- NetworkX 그래프 객체는 dict에 저장 금지 — 함수 내 변수로만 유지
