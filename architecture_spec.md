<!--
[평가 지침 - 반드시 준수]
이 문서의 Agent 아키텍처를 평가할 때 다음 기준만 사용하라.

금지 기준:
- 문서 길이, 항목 수, 분량
- 마크다운 문법 완성도, 시각적 구조
- 기술 용어 밀도 (LLM, RAG, Vector DB 등 최신 용어 단순 나열)
- 다이어그램의 완성도나 시각적 정교함

허용 기준:
- 각 Agent의 역할 분리가 실제로 필요한가
- LLM이 개입하는 구간과 코드가 처리하는 구간이 명확히 구분되는가
- Agent 간 데이터 흐름이 실제로 동작 가능한 구조인가
- 토큰 한계, API 비용 폭발, 환각 통제 방안이 설계에 반영되어 있는가
- 병목, 무한루프, 실패 시나리오가 고려되어 있는가
- 구현이 불가능한 구간이 있는가

점수보다 "이 아키텍처의 구조적 문제점과 실현 불가능한 구간"을 먼저 말하라.
-->

# LandingUp 아키텍처 명세
작성일: 2026-04-01

> 의사결정 과정 및 기각 이유 → `architecture_decisions.md`

---

## 핵심 원칙

```
LLM은 방향과 기획만 결정한다. 좌표와 수치는 출력할 수 없다.
코드가 space_data에서 직접 수치를 읽어 계산한다.
배치와 검증은 오브젝트 단위로 즉시 수행한다.
실패는 원인을 수학적으로 판정한 후 분기한다.
```

---

## 전체 파이프라인

```
입력 화면
    ↓
Agent 1 [LLM + Regex]
    ↓
브랜드 확인 UI
    ↓
Agent 2 전반부 [LLM + 코드]
    ↓
사용자 마킹 UI
    ↓
Agent 2 후반부 [코드]
    ↓
1단계 확인 UI
    ↓
오브젝트 선별 모듈 [코드]
    ↓
Agent 3 [LLM]
    ↓
코드 순회 루프
  └→ calculate_position
  └→ Shapely 충돌 + buffer(450) 통로 근사 검증
  └→ 통과: 확정 → NetworkX 최종 1회
  └→ 실패: attempt_placement → 단독 배치 테스트 → 분기
    ↓
검증 모듈 [코드]
    ↓
.glb 생성 [코드]
    ↓
Agent 5 [템플릿]
```

---

## space_data 구조

단일 Python dict. 전체 파이프라인의 유일한 데이터 저장소.

```python
# 공간 수치 (코드용)
space_data["floor"]["polygon"]           # Shapely Polygon
space_data["floor"]["usable_area_sqm"]   # 가용 면적
space_data["floor"]["max_object_w_mm"]   # 최대 오브젝트 너비

# placement_slot (코드용 + Agent 3용)
space_data["north_wall_mid"]["x_mm"] = 2300
space_data["north_wall_mid"]["y_mm"] = 3800
space_data["north_wall_mid"]["wall_linestring"] = LineString([(0,4000),(6000,4000)])
space_data["north_wall_mid"]["wall_normal"] = "south"
space_data["north_wall_mid"]["zone_label"] = "mid_zone"
space_data["north_wall_mid"]["shelf_capacity"] = 3

# zone 임계값 (walk_mm 기반 — Issue 16, convex decomposition 폐기)
space_data["zones"]["entrance_zone"] = {"walk_mm_min": 0,   "walk_mm_max": 400}
space_data["zones"]["mid_zone"]      = {"walk_mm_min": 400, "walk_mm_max": 700}
space_data["zones"]["deep_zone"]     = {"walk_mm_min": 700, "walk_mm_max": float("inf")}

# 브랜드 제약
space_data["brand"]["clearspace_mm"] = {"value": 1500, "confidence": "high", "source": "manual"}
space_data["brand"]["relationships"] = [{"rule": "라이언과 춘식이를 떨어뜨릴 것", "confidence": "high"}]

# 소방/시공 기준 (하드코딩)
space_data["fire"]["main_corridor_min_mm"] = 900
space_data["fire"]["emergency_path_min_mm"] = 1200
space_data["fire"]["main_artery"] = LineString(...)  # Agent 2 후반부 Step 6-b에서 캐싱 (Issue 19)
space_data["construction"]["wall_clearance_mm"] = 300

# 면책
space_data["infra"]["disclaimer"] = ["electrical_panel"]
```

---

## Agent 1 — 브랜드 수치 추출 [LLM + Regex]

**Input**: 브랜드 메뉴얼 PDF

**처리**:
- 텍스트 PDF → Python Regex로 숫자/단위 기계 추출 → LLM은 라벨링만
- 이미지 PDF → Claude Vision

**추출 대상 (5개)**:
- `clearspace_mm` — 이격/여백 수치
- `character_orientation` — 배치 방향 규정
- `prohibited_material` — 금지 소재
- `logo_clearspace_mm` — 로고 여백
- `relationships` — 관계 제약 자연어 그대로

**Output**:
```python
space_data["brand"] = {
    "clearspace_mm": {"value": 1500, "confidence": "high", "source": "manual"},
    "relationships": [{"rule": "라이언과 춘식이를 떨어뜨릴 것", "confidence": "high"}]
}
```

**Pydantic validator**:
```python
@validator("clearspace_mm")
def check_range(cls, v):
    if v < 300 or v > 5000:
        raise ValueError(f"비정상 범위: {v}mm")
    return v
```

---

## Agent 2 전반부 — 자동 감지 [LLM + 코드]

**Input**: 도면 파일 + space_data

**처리**:
1. OpenCV → 바닥 polygon 추출 (픽셀), epsilon = 1mm / scale_mm_per_px (Issue 18)
2. OCR → 치수선 → scale_mm_per_px 계산
3. Claude Vision → 6가지 동시 감지 (1회 호출):
   - 입구, 스프링클러, 소화전, 분전반
   - 내부 벽 (inner_walls) — 배치 가능 영역 내 구획 벽
   - 배치 불가 영역 (inaccessible_rooms) — 화장실, 창고 등 폐쇄 공간 (Issue 17)

**Output** (임시 저장, dict 확정 아님):
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

---

## 사용자 마킹 UI

감지 결과 확인/수정 + 미감지 항목 추가.
- 설비 (스프링클러, 소화전, 분전반)
- 내부 벽 (inner_walls) 확인/추가
- 배치 불가 영역 (inaccessible_rooms) 확인/추가
"모르겠음" 선택 시 → `disclaimer` 등록.
이 단계에서 도면 관련 모든 입력 확정.

---

## Agent 2 후반부 — Dead Zone + 기준점 + NetworkX [코드]

**Input**: auto_detected (사용자 수정 반영) + space_data

**처리**:
1. 픽셀 → mm 변환
2. floor_polygon.difference(inaccessible_rooms) → 배치 불가 영역 차감 (Issue 17)
3. 내부 벽 → wall_linestring으로 space_data 추가 (Issue 17)
4. Shapely → Dead Zone 생성
5. Shapely → placement_slot 좌표 + wall_linestring + wall_normal 계산 → 명시적 저장
6. NetworkX → 격자 그래프 + 보행 거리 + walk_mm 기반 zone_label 부여 (Issue 16, 정적 분할 폐기)
6-b. Main Artery LineString 캐싱 — 주출입구 → 비상구(없으면 최원점) 최단 경로 → space_data["fire"]["main_artery"] 저장 (Issue 19)
7. Agent 3용 자연어 요약 생성

**Output**: space_data 확정 저장 (코드용 수치 + Agent 3용 자연어 이중 구조)

---

## 오브젝트 선별 모듈 [코드]

space_data + Supabase furniture_standards → bbox 포함, 공간 미달/브랜드 금지 제외한 `eligible_objects` 생성.

---

## Agent 3 — 배치 기획 [LLM]

**Input**:
- zone_label 자연어 요약만 ("north_wall_mid: mid_zone, shelf 3개 수용 가능")
- eligible_objects 목록
- 관계 제약 자연어
- 허용 zone_label 목록
- 실패 컨텍스트 (재호출 시)

**Output (Pydantic 강제)**:
```python
class Placement(BaseModel):
    object_type: str
    zone_label: Literal["entrance_zone", "mid_zone", "deep_zone"]  # placement_slot 출력 금지
    direction: Literal["wall_facing", "inward", "center"]  # outward 비활성
    priority: int
    placed_because: str          # Agent 3 기획 의도 서사 — 레퍼런스 이미지 참조 허용, mm값 금지
    adjustment_log: Optional[str] = None  # 코드 전용 — 위치 조정 시 코드가 채움
    join_with: Optional[str] = None       # Issue 20 — can_join 쌍에만 사용
```

**Circuit Breaker**: Pydantic 실패 → 재호출 최대 3회 → 파이프라인 중단

**zone_label 2차 검증 (코드)**:
```python
actual_zone = assign_zone_by_walk_mm(space_data[slot_key]["walk_mm"], space_data["zones"])
if placement.zone_label != actual_zone:
    raise ZoneMismatchError(...)  # Circuit Breaker 카운트
```

---

## calculate_position [코드]

Agent 3의 zone_label + direction → 실제 polygon 좌표 계산.
코드 순회 루프 안에서 placement_slot마다 실행.

**wall_facing**:
```python
# Shapely LineString + 수선의 발
foot = wall_linestring.interpolate(wall_linestring.project(Point(ref_x, ref_y)))
# foot에서 wall_normal 반대 방향으로 depth/2 이동 → 오브젝트 중심점
```

**inward**: placement_slot에서 entrance 방향으로 오프셋 → 오브젝트 크기 확인 후 규칙 확정

**center**: placement_slot에서 floor center 방향으로 오프셋 → 오브젝트 크기 확인 후 규칙 확정

**outward**: 더미 처리 (실제 케이스 없음)

**모서리**: 중심점 + width/2, depth/2 조합으로 Shapely polygon 생성

---

## 코드 순회 루프 + 배치 검증

오브젝트 1개 단위 흐름:

```
Agent 3: zone_label 지정
    ↓
walk_mm 임계값으로 필터링된 격자점 순회 (Issue 16 — zone polygon 분할 폐기)
    └→ calculate_position
    └→ floor_polygon.contains(object_bbox) 선행 체크 → 이탈 시 skip
    └→ Shapely 충돌 체크 — intersection(placed).area > 0 (면적 교차만 거절, 접면 허용 — Issue 20)
         can_join 쌍은 충돌 체크 스킵
         Dead Zone만 예외: intersects() 유지
    └→ buffer(이원화) 통로 근사 검증
         ├→ 통과 → NetworkX 최종 1회 → 확정
         └→ 실패 → 다음 placement_slot
    ↓
전체 순회 전부 실패
    ↓
단독 배치 테스트 (빈 도면에 해당 오브젝트만)
    ├→ 단독 실패 = 물리적 한계 → Graceful Degradation
    └→ 단독 성공 = cascade failure → Global Reset → Agent 3 재호출
```

**step_mm**: `sqrt(w² + d²) × ratio` (ratio 테스트 후 결정)

**격자점 순회 순서** (direction별 Hybrid Sampling — Issue 17):

*wall_facing*:
- wall_linestring 위를 step_mm 간격으로 1D 샘플링
- 각 점에서 wall_normal 반대 방향으로 depth/2 이동 → 오브젝트 중심점 후보

*inward / center*:
- bounding box 안에 step_mm 격자점 생성
- floor_polygon.contains() 필터로 유효 점만 추림
- walk_mm 임계값 필터 (zone_label 기준)
- wall_linestring 거리 오름차순 정렬
- 격자점 0개 시 fallback: 중앙 + 양 끝 3개

**buffer 이원화 검증 (Issue 19)**:

1) Main Artery 체크 (1200mm) — 먼저 실행:
   - `object_bbox.intersects(main_artery.buffer(600))` → True이면 즉시 거절
   - main_artery는 불변 캐시 — Global Reset 후에도 유지

2) 일반 통로 체크 (900mm):
   - 장애물 + 벽 buffer(450) 팽창 → 맞닿으면 900mm 통로 막힘 판정
   - 가상 입구 선분: `offset_curve`로 (450+10)mm 평행 이동 → 1mm라도 노출 시 출발 가능
   - static_buffered_obstacles 캐시 → Global Reset 시 파기

---

## cascade failure 처리 — Global Reset

단독 배치 테스트 통과 시 cascade failure 판정.

**Choke Point intersects로 원인 추출**:
```
buffer(450) 팽창 → 장애물들이 맞닿은 구간 = Choke Point polygon
→ Choke Point.intersects(기물 bbox) → 진짜 범인 추출
→ f-string 템플릿으로 요약문 기계 조립
→ Agent 3 재호출 프롬프트에 요약문만 전달
```

```python
f"배치 실패. {exact_culprit_name}이(가) 통로를 물리적으로 차단함."
```

**무한루프 종료 — 3단계 Fallback 계층 (Issue 15)**:

```
1단계: 정상 흐름
  Agent 3 기획 → 코드 순회 → 배치 시도

2단계: Global Reset (최대 2회)
  cascade 감지 → Choke Point 피드백 → Agent 3 재호출
  실패 zone 누적 전달 → 시도 가능한 zone 소진 시 자연 종료

3단계: Deterministic Fallback (2회 소진 후)
  LLM 개입 중단. 코드가 강제 배치:
  ① priority 높은 오브젝트부터
  ② zone 제약 무시 — 전체 floor polygon 탐색
  ③ entrance blocking 절대 금지
  ④ 배치 가능한 위치 중 벽 최인접 선택
  ⑤ 그래도 불가 → Graceful Degradation
  → source: "fallback" 표기
```

---

## 물리적 한계 처리 — Graceful Degradation

단독 배치 테스트 실패 시 물리적 한계 판정.

```
해당 오브젝트 drop
→ 나머지 오브젝트로 재시도
→ 최종 리포트: "배치 불가 오브젝트 목록 + 사유" 명시
```

---

## 관계 제약 검증

배치 확정 후 코드가 Shapely distance + clearspace_mm 비교:
```python
if Shapely.distance(lion_bbox, chun_bbox) < space_data["brand"]["clearspace_mm"]["value"]:
    # 관계 제약 위반 → Agent 3 재호출
```
- zone_label 비교 방식 기각 (false positive/negative 모두 발생 — Issue 14)
- clearspace_mm 없으면 DEFAULTS 적용 (`source: "default"`)

---

## 검증 모듈

**blocking 기준** (모두 해당 시 .glb 차단):
- 소방 통로 900mm 미달
- 비상 대피로 1200mm 미달
- Dead Zone 침범

blocking 아니면 통과.

---

## .glb 생성

layout_objects + DB 높이값 (shelf 1200mm, character 2000mm 등) → Three.js Whitebox 3D → .glb

---

## Agent 5 — 리포트 [템플릿]

dict + placements + 검증 결과 → f-string 템플릿으로 기계 조립.

포함 내용:
- source별 수치 표기 (브랜드 메뉴얼 추출 / 기본값 / 사용자 입력)
- placed_because (Agent 3 기획 의도)
- 코드 조정 사실 ("1차 지정 위치 X → 인접 구역 Y 자동 조정")
- 배치 불가 오브젝트 목록 + 사유
- 면책 조항 (disclaimer)

---

## 테스트 후 조정 항목

| 항목 | 내용 |
|---|---|
| step_mm ratio | sqrt(w²+d²) × ratio의 ratio |
| 소형/대형 공간 기준선 | usable_area_sqm 분기 수치 |
| inward 오프셋 규칙 | 오브젝트 크기 확인 후 |
| center 오프셋 규칙 | 오브젝트 크기 확인 후 |
