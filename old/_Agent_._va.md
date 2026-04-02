# 랜딩업 — Agent 세부 구조 및 계산 로직 va
작성일: 2026-04-01

> v4.1 대비 변경:
> 트리플 스토어 → dict /
> Agent 2 분리 (전반부: 감지 / 후반부: 계산) /
> 사용자 마킹 계산 이전 이동 /
> 브랜드 확인 입력 화면 이동 /
> Agent 1 추출 전략 상세화 (confidence/source/relationships/validator) /
> Agent 3 피드백에 placed_objects 추가 /
> NetworkX 그래프 스냅샷 제외 (재생성 방식) /
> Agent 4 MVP 후순위 / Agent 5 MVP 템플릿

---

## 핵심 설계 원칙

```
LLM은 수학 계산을 하지 않는다.
LLM은 방향과 우선순위만 결정한다.
수치는 전부 Shapely/NetworkX가 계산하고 dict에 저장한다.
Agent 3은 자연어 요약만 읽고, 수치는 출력할 수 없다.
Shapely는 Agent 3 출력의 키이름으로 dict에서 원본 수치를 직접 조회한다.
배치와 통로 검증은 오브젝트 단위로 동시에 수행된다.
Agent 3 재호출은 코드 레벨 위치 조정이 불가한 경우에만 발생한다.
오브젝트의 물리적 속성(bbox)은 DB에서 온다.
```

---

## 전체 구조 한눈에 보기

```
[입력 화면]                                도면+메뉴얼 업로드
    ↓
Agent 1                                    브랜드/기준법 수치 추출 + 사용자 확인  [LLM]
    ↓ [dict 저장]
Agent 2 전반부                             OpenCV + OCR + Vision 자동 감지       [LLM + 코드]
    ↓ [임시 저장]
[사용자 마킹]                              입구 확인 + 설비 추가
    ↓
Agent 2 후반부                             Dead Zone + NetworkX 계산             [코드]
    ↓ [dict 저장 완료]
── 1단계 사용자 확인 (결과 확인만) ──
    ↓
[오브젝트 선별 모듈]                       dict + DB 기반 필터링                 [코드]
    ↓
Agent 3                                    자연어 판단 / Pydantic 출력 강제      [LLM]
    ↓ [Pydantic 검증]
[Shapely 배치 계산 + 증분 NetworkX 검증]   오브젝트 단위 배치 + 즉시 통로 체크   [코드]
    실패 → 코드 위치 조정 → 불가 시 Agent 3 재호출 (placed_objects 포함)
    ↓
[검증 모듈] Shapely                        법적 최종 확인                        [코드]
    ↓
[구조화 모듈] Three.js                     .glb 생성                             [코드]
    ↓
Agent 4                                    MVP 후순위                            [LLM]
    ↓
Agent 5                                    MVP: 템플릿                           [템플릿]
```

---

## dict 구조

단일 Python dictionary. 키-값 기반 직접 조회.

```python
space_data = {}

# 단일 수치
space_data["entrance"] = {"x_mm": 0, "y_mm": 1000}
space_data["north_wall_mid"] = {"x_mm": 2300, "y_mm": 3800}

# 배열 데이터
space_data["floor"] = {"polygon": [[0,0],[6000,0],[6000,4000],...]}
space_data["sprinkler_1"] = {"center_mm": [1500, 2000], "radius_mm": 2300}

# 브랜드 제약 (confidence + source 포함)
space_data["brand"] = {
    "clearspace_mm": {"value": 1500, "confidence": "high", "source": "manual"},
    "relationships": [{"rule": "라이언과 춘식이 떨어뜨릴 것", "confidence": "high"}]
}

# 하드코딩 (법 고정값)
space_data["fire"] = {"main_corridor_min_mm": 900, "emergency_path_min_mm": 1200}
space_data["construction"] = {"wall_clearance_mm": 300, "object_gap_mm": 300}
```

조회:
```python
x = space_data["entrance"]["x_mm"]              # → 0
polygon = space_data["floor"]["polygon"]         # → [[0,0],...]
clearspace = space_data["brand"]["clearspace_mm"]["value"]  # → 1500
```

---

## Agent 1 — 브랜드/기준법 수치 추출

### 역할

도면 분석 이전에 고정 제약값을 먼저 확정. Agent 2 후반부 Shapely가 이 수치를 파라미터로 사용. 입력 화면에서 추출 결과를 사용자에게 즉시 확인받음.

### 입력

```
브랜드 메뉴얼 PDF (Claude Document API)
소방법/시공기준 → 하드코딩
```

### 추출 대상 (5개만)

```
1. clearspace_mm (여백/이격/띄움/여유 공간) → mm 통일
2. character_orientation (배치 방향/정면/향하도록) → "입구 정면"/"벽면"/"자유" 정규화
3. prohibited_material (금지 소재/사용 불가) → 소재명
4. logo_clearspace_mm (로고 여백/로고 주변) → mm 통일
5. relationships (관계 제약 — 수치 없는 규정) → 자연어 그대로
```

### 프롬프트 규칙

```
- 캐릭터명/IP명/마스코트명 → 모두 character_bbox로 간주
  (무명 캐릭터도 "조형물", "피규어", "스탠딩" 등 배치 대상 고유명사면 포함)
- 동의어 처리 ("이격" = "띄움" = "여백" = "멀리" = "클리어스페이스")
- 문서에 없는 수치 → null (추측 금지)
- confidence 반환 (high / medium / low)
```

### 출력: dict 저장

```python
space_data["brand"] = {
    "clearspace_mm": {"value": 1500, "confidence": "high", "source": "manual"},
    "character_orientation": {"value": "입구 정면", "confidence": "high", "source": "manual"},
    "prohibited_material": {"value": "금속", "confidence": "medium", "source": "manual"},
    "logo_clearspace_mm": {"value": None, "confidence": None, "source": None},
    "relationships": [
        {"rule": "라이언과 춘식이를 떨어뜨릴 것", "confidence": "high"}
    ]
}

# null → 기본값 merge
DEFAULTS = {"clearspace_mm": 1000, "logo_clearspace_mm": 500}
for key, default in DEFAULTS.items():
    if space_data["brand"][key]["value"] is None:
        space_data["brand"][key] = {"value": default, "confidence": "default", "source": "default"}

# 소방법/시공기준 하드코딩
space_data["fire"] = {"main_corridor_min_mm": 900, "emergency_path_min_mm": 1200}
space_data["construction"] = {"wall_clearance_mm": 300, "object_gap_mm": 300}
```

### 값 범위 validator (오탈자 방어)

```python
class BrandConstraints(BaseModel):
    clearspace_mm: int
    logo_clearspace_mm: int

    @validator("clearspace_mm")
    def check_clearspace(cls, v):
        if v < 300 or v > 5000:
            raise ValueError(f"clearspace {v}mm 비정상 범위")
        return v

    @validator("logo_clearspace_mm")
    def check_logo(cls, v):
        if v < 100 or v > 3000:
            raise ValueError(f"logo_clearspace {v}mm 비정상 범위")
        return v
```

### Circuit Breaker

```python
class Agent1Output(BaseModel):
    clearspace_mm: Optional[int]
    character_orientation: Optional[str]
    prohibited_material: Optional[str]
    logo_clearspace_mm: Optional[int]
    relationships: list[dict]
```

### 사용자 확인 (입력 화면)

```
Agent 1 실행 후 즉시 표시:
  clearspace_mm: 1500mm         ✅ 확인 / ✏️ 수정
  금지 소재: 금속                ✅ / ✏️
  로고 여백: 미추출 → 기본값     ✅ / ✏️
  관계: "라이언과 춘식이 떨어뜨릴 것"  ✅ / ✏️
  confidence low 항목 → 하이라이트

사용자 수정 시:
  source → "user_corrected"
```

---

## Agent 2 전반부 — 자동 감지

### 역할

도면에서 자동으로 뽑을 수 있는 것만 뽑음. 계산 안 함. 사용자 마킹 대기.

### Step 1 — OpenCV: polygon 추출

```python
img = cv2.imread(floor_plan_image)
gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
edges = cv2.Canny(gray, 50, 150, apertureSize=3)
contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
floor_contour = max(contours, key=cv2.contourArea)
polygon_pixels = floor_contour.squeeze().tolist()
```

### Step 2 — OCR: 스케일 계산

```python
for region in dimension_regions:
    text = pytesseract.image_to_string(region, config='--psm 7 digits')
    dimension_mm = parse_dimension(text)
    if dimension_mm:
        scale = dimension_mm / pixel_length
        scale_confidence = 0.95
        break
```

### Step 3 — Claude Vision: 입구 + 설비 동시 감지

```
입구 위치 (문 기호, 화살표, "입구" 텍스트)
스프링클러 기호 + 살수 반경
소화전 위치
배전함/분전반 위치
미감지 항목 → 빈 배열
```

### 임시 저장 (dict 확정 아님)

```python
auto_detected = {
    "floor_polygon_px": polygon_pixels,
    "scale_mm_per_px": scale,
    "scale_confidence": scale_confidence,
    "entrance": {"x_px": 0, "y_px": 100, "confidence": "high"},
    "sprinklers": [{"x_px": 150, "y_px": 200, "confidence": "high"}],
    "fire_hydrant": [],
    "electrical_panel": [],
}
```

**여기서 멈춤.** Dead Zone 계산 안 함.

---

## 사용자 마킹

```
도면 위 오버레이:
  ✅ 감지 항목 → 확인/수정 (드래그)
  ❓ 미감지 항목 → 클릭 추가 or "모르겠음"

사용자 마킹:
  auto_detected["fire_hydrant"].append({"x_px": 320, "y_px": 150, "confidence": "user_input"})

"모르겠음":
  auto_detected["disclaimer"] = ["fire_hydrant", "electrical_panel"]

감지 수정:
  auto_detected["entrance"]["confidence"] = "user_corrected"
```

---

## Agent 2 후반부 — Dead Zone + 기준점 + NetworkX

### 역할

사용자 마킹 합산된 최종 데이터로 한 번에 계산. 재계산 없음.

### Step 1 — px → mm 변환

```python
scale = auto_detected["scale_mm_per_px"]
floor_polygon_mm = [[int(x * scale), int(y * scale)] for x, y in auto_detected["floor_polygon_px"]]
```

### Step 2 — Shapely: Dead Zone + 기준점

```python
floor = Polygon(floor_polygon_mm)
wall_clearance = space_data["construction"]["wall_clearance_mm"]
entrance_buffer = space_data["fire"]["main_corridor_min_mm"] * 1.5

dead_zones = []
# 자동 감지 + 사용자 마킹 전부 포함
for s in auto_detected["sprinklers"]:
    s_mm = px_to_mm(s, scale)
    dead_zones.append(Point(s_mm['x'], s_mm['y']).buffer(2300))
for fh in auto_detected["fire_hydrant"]:
    fh_mm = px_to_mm(fh, scale)
    dead_zones.append(Point(fh_mm['x'], fh_mm['y']).buffer(1000))

dead_zone_union = unary_union(dead_zones) if dead_zones else None

# reference_points 계산
reference_points = {
    "entrance": {"x": entrance_mm['x'], "y": entrance_mm['y']},
    "north_wall_mid": compute_wall_mid(floor_usable, 'north'),
    ...
}
```

### Step 3 — NetworkX: 격자 그래프 + 보행 거리

```python
G_base = build_grid_graph(floor_usable, grid_size=100)
entrance_node = find_nearest_node(G_base, entrance_mm['x'], entrance_mm['y'])
walk_distances = compute_walk_distances(G_base, entrance_node, reference_points)
```

### Step 4 — dict 저장 (두 형태)

```python
# 코드용 (수치)
space_data["floor"]["polygon"] = floor_polygon_mm
space_data["floor"]["usable_area_sqm"] = floor_usable.area / 1e6
space_data["entrance"]["x_mm"] = entrance_mm['x']
space_data["entrance"]["y_mm"] = entrance_mm['y']
for key, pt in reference_points.items():
    space_data[key]["x_mm"] = int(pt['x'])
    space_data[key]["y_mm"] = int(pt['y'])

# Agent 3용 (자연어)
for key, walk_mm in walk_distances.items():
    space_data[key]["zone_label"] = to_zone_label(walk_mm)
    space_data[key]["walk_distance_mm"] = walk_mm

# 면책
space_data["infra"] = {"disclaimer": auto_detected.get("disclaimer", [])}
```

### NetworkX 그래프 저장 방식 (va 변경)

```
G_base는 dict에 저장하지 않음 (JSON 직렬화 불가).
함수 내부에서 변수로 유지하고 Shapely 배치 모듈에 직접 전달.
Supabase 스냅샷 저장 시 NetworkX 관련 항목 skip.
복원 필요 시 floor_polygon + placed_polygons로 재생성.
```

---

## [오브젝트 선별 모듈]

(v4.1과 동일)

```python
eligible_objects = []
max_w = space_data["floor"]["max_object_w_mm"]
max_d = space_data["floor"]["max_object_d_mm"]

for obj in all_objects:
    if obj['width_mm'] > max_w: continue
    if obj['depth_mm'] > max_d: continue
    if conflicts_with_brand(obj, space_data["brand"]): continue
    eligible_objects.append(obj)
```

---

## Agent 3 — 배치 의도 결정

### 수치 차단 구조

(v4.1과 동일 — dict로 변경된 것만 반영)

```
프롬프트:
  자연어 요약 제공:
    "entrance: entrance_zone, walk 0mm"
    "north_wall_mid: mid_zone, shelf 3개 수용 가능"
  관계 제약: "라이언과 춘식이 떨어뜨릴 것"
  "좌표·mm값 출력 금지"
  허용 키 목록 (동적 생성)
```

### 출력 스키마

```python
valid_refs = list(reference_points.keys())

class PlacementDirective(BaseModel):
    object_type: str
    reference_point: str
    direction: Literal["inward", "wall_facing", "entrance_facing", "freestanding"]
    priority: int
    placed_because: str

class Agent3Output(BaseModel):
    placements: list[PlacementDirective]

    @validator('placements')
    def check_reference_points(cls, placements):
        for p in placements:
            if p.reference_point not in valid_refs:
                raise ValueError(f"허용되지 않는 reference_point: {p.reference_point}")
        return placements
```

---

## [Shapely 배치 계산 + 증분 NetworkX 검증]

### 메인 루프

```python
def place_with_incremental_validation(agent3_output, space_data, eligible_objects, G_base, entrance_node):
    layout_objects = []
    placed_polygons = []
    G = G_base.copy()

    for directive in sorted(agent3_output.placements, key=lambda x: x.priority):
        obj_spec = find_object(directive.object_type, eligible_objects)
        result = attempt_placement(obj_spec, directive, placed_polygons, G, entrance_node, space_data)

        if result.success:
            layout_objects.append(result.obj)
            placed_polygons.append(result.polygon)
            G = update_graph(G, result.polygon)
        else:
            adjusted = try_position_adjustment(obj_spec, directive, placed_polygons, G, entrance_node, space_data)
            if adjusted.success:
                layout_objects.append(adjusted.obj)
                placed_polygons.append(adjusted.polygon)
                G = update_graph(G, adjusted.polygon)
            else:
                return PlacementFailure(
                    object_type=directive.object_type,
                    reference_point=directive.reference_point,
                    reason=adjusted.failure_reason,
                    placed_objects=[
                        {"object_type": o["type"], "reference_point": o["reference_point"]}
                        for o in layout_objects
                    ],
                    alternative_refs=suggest_alternatives(G, obj_spec, space_data)
                )

    return layout_objects
```

### attempt_placement

```python
def attempt_placement(obj_spec, directive, placed_polygons, G, entrance_node, space_data):
    w, d = obj_spec['width_mm'], obj_spec['depth_mm']
    object_gap = space_data["construction"]["object_gap_mm"]
    min_corridor = space_data["fire"]["main_corridor_min_mm"]

    ref_x = space_data[directive.reference_point]["x_mm"]
    ref_y = space_data[directive.reference_point]["y_mm"]

    position = calculate_position(ref_x, ref_y, directive.direction, w, d, object_gap, space_data)
    obj_polygon = create_object_polygon(position, w, d)

    # Shapely 충돌 체크
    for placed in placed_polygons:
        if obj_polygon.intersects(placed):
            return PlacementResult(success=False, reason="shapely_collision")

    # Dead Zone 체크
    dead_zone_union = compute_dead_zone_union(space_data)
    if dead_zone_union and obj_polygon.intersects(dead_zone_union):
        return PlacementResult(success=False, reason="dead_zone_collision")

    # NetworkX 통로 체크
    G_temp = update_graph(G.copy(), obj_polygon)
    if not check_corridor_width(G_temp, entrance_node, min_width=min_corridor):
        return PlacementResult(success=False, reason="corridor_blocked")

    return PlacementResult(success=True, obj=build_obj(obj_spec, position, directive), polygon=obj_polygon)
```

### Agent 3 재호출 피드백 (va 변경)

```python
feedback_to_agent3 = {
    "failed_object": "shelf_rental",
    "failed_reference_point": "north_wall_mid",
    "reason": "corridor_blocked",
    "max_available_w_mm": 1200,
    "placed_objects": [
        {"object_type": "character_bbox", "reference_point": "entrance"},
        {"object_type": "photo_zone", "reference_point": "inner_corner"}
    ],
    "alternative_references": [
        {"key": "south_wall_mid", "zone_label": "mid_zone", "shelf_capacity": 2}
    ]
}
```

placed_objects 추가 이유: 점유된 reference_point를 알려줘야 Agent 3이 재지시 시 충돌 회피.

---

## [검증 모듈]

(v4.1과 동일 — dict 키 접근만 변경)

```python
min_corridor = space_data["fire"]["main_corridor_min_mm"]
emergency_path = space_data["fire"]["emergency_path_min_mm"]

# blocking이면 차단, 아니면 통과 (MVP)
```

---

## [구조화 모듈] — Three.js

(v4.1과 동일)

```javascript
const MM_TO_UNIT = /* 스프린트 2 기획회의 확정 */;
// 높이는 DB 저장값 사용
// 높이 간섭은 SketchUp에서 확인 (리포트 기재)
```

---

## JSON Circuit Breaker — 전 Agent 공통

(v4.1과 동일)

---

## Supabase 테이블 구조

```
furniture_standards
  id, type, name, layer
  width_mm, depth_mm, height_mm
  direction, install_condition
  popup_type_tags[], rental_available

construction_rules
  item, standard_value, unit, violation_severity

agent_logs
  id, project_id, agent_name
  input_json, output_json
  pydantic_errors, retry_count
  duration_ms, called_at

dict_snapshot
  project_id, snapshot_json, created_at
  (NetworkX 그래프 제외 — 재생성 방식)

placement_adjustment_logs
  project_id, object_type, reference_point
  failure_reason, adjustment_success
  steps_tried, final_position_mm
  called_at
```

---

## 스프린트 2 기획회의 미결 사항

### 치명적

```
단위 변환 상수:
  1 unit = 1mm vs 1 unit = 100mm
  → geometry_utils.js MM_TO_UNIT 고정

calculate_position 방향별 오프셋 명세:
  wall_facing / inward / entrance_facing 오프셋 기준점 확정
```

### 높음

```
증분 검증 위치 조정 파라미터:
  step_mm: 50 / 100 / 200mm
  max_steps: 5 / 10 / 20
  스프린트 3 실측, 스프린트 5 재조정

배치 실패 후 부분 출력 기준

Agent 3 재호출 후 재배치 범위:
  실패 오브젝트만 vs 전체 재시작

오브젝트 DB 초기 데이터 입력:
  furniture_standards 5~10개
```
