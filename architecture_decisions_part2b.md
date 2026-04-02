# Architecture Decisions — Part 2b (Issue 17-22 + 미결)

> Part 1: architecture_decisions_part1.md | Part 2a: architecture_decisions_part2a.md

## Issue 17. 내부 벽/방 구분 + 복수 입구

**문제**: 현재 설계는 "하나의 바닥 polygon + 입구 1개"를 전제. 실제 공간에는 내부 벽, 폐쇄된 방(사무실, 화장실 등), 복수 입구가 존재.

```
현재 설계가 다루는 것:
┌────────────────┐
│                │
│   오픈 플로어   │ ← 입구 1개
│                │
└────────────────┘

실제로 다뤄야 하는 것:
┌────┬───────────┐
│ 방 │           │
├────┘  배치 가능 │ ← 입구 A
│      영역      │
│     ┌──────────┤
│     │ 창고     │ ← 입구 B
└─────┴──────────┘
```

**부재한 것**:
1. **배치 가능 영역 분류**: 전체 polygon에서 폐쇄된 방(사무실, 화장실, 창고)을 제외한 "배치 가능 영역"을 추출하는 규칙 없음
2. **내부 벽 처리**: 내부 벽이 Dead Zone인지, zone 경계인지, 무시 대상인지 정의 없음
3. **복수 입구**: 소방 통로 검증 시 입구가 2개 이상이면 경로 계산이 달라짐. buffer 근사의 가상 입구 선분도 복수 생성 필요
4. **좁은 복도**: 방과 방 사이 복도에 격자점이 아예 안 생기는 케이스 — zone 분할 + 격자 순회에서 누락 가능

**확정 — 하위 문제 4: 좁은 복도 격자점 누락 → Hybrid Sampling**

방향별로 격자 탐색 방식을 분리:

- **wall_facing**: `wall_linestring` 위를 `step_mm` 간격으로 1D 샘플링 → depth/2 법선 방향 오프셋으로 오브젝트 중심점 계산
  - 격자 기반이 아니므로 복도 폭 무관하게 항상 후보 생성
  - 2D 격자 탐색 적용하지 않음

- **inward / center**: 기존 2D grid (`floor_polygon` bounding box 전체) + `walk_mm` 임계값 필터 유지
  - 벽과 무관한 자유 배치 오브젝트 → 2D 격자 탐색이 적합

```
wall_facing:
    wall_linestring 위를 step_mm 간격으로 점 추출
    → 각 점에서 wall_normal 반대 방향으로 depth/2 이동
    → 오브젝트 중심점 후보 생성

inward / center:
    floor_polygon bounding box → step_mm 격자점 생성
    → floor_polygon.contains() 필터
    → walk_mm 임계값 필터 (zone_label 기준)
    → wall_linestring 거리 오름차순 정렬
```

**미결 (하위 문제 1–3)**: 전체 아키텍처 수준의 결정 필요. 단순 미결이 아니라 Agent 2 전반부(감지) + 후반부(계산) + 검증 모듈 전부에 영향.

1. **배치 가능 영역 분류**: Agent 2 Vision이 내부 벽 감지 시도 → 사용자 마킹 UI에서 "배치 불가 영역" 확인/추가 → Agent 2 후반부에서 `floor_polygon.difference(room_polygons)` 처리. **확정.**

2. **내부 벽 처리**: Agent 2 Vision 감지 대상에 내부 벽 추가 → 사용자 마킹 UI에서 확인/수정 → 방을 완전히 둘러싸는 내부 벽은 sub-problem 1과 동일하게 floor_polygon 차감. 배치 가능 영역 내 내부 벽은 wall_linestring으로 space_data에 추가. **확정.**
3. **복수 입구**: Issue 16 NetworkX walk_mm으로 자연 처리됨. `walk_mm = min(distance from each entrance)` — super-source 노드 or min() 호출로 구현. 가상 입구 선분은 리스트로 복수 생성, 하나라도 노출되면 통과. **별도 아키텍처 결정 불필요.**

---

## Issue 18. 곡선 벽 polyline 근사 — 오차 허용 기준

**문제**: Issue 8에서 벽을 LineString으로 표현하기로 했고, 곡선 벽은 짧은 직선 다수로 근사(polyline)하면 된다고 판단했으나, 오차 수치를 정의하지 않음.

**오차 수치 (반지름 3000mm 곡선 기준)**:

| 세그먼트 수 | 최대 오차 | 소방 통로 900mm 경계에서의 위험 |
|---|---|---|
| 50개 | ~6mm | 통과/차단 판정 뒤집힐 수 있음 |
| 100개 | ~1.5mm | 시공 오차(±3~10mm) 이내 |
| 200개 | ~0.4mm | 오차 무시 가능 |

**문제의 본질**: 소방 통로 최소 폭(900mm)은 법적 기준이라 오차 허용이 사실상 없음. polyline 근사 오차가 900mm 경계선에서 buffer(450) 판정을 뒤집으면 — 실제로는 막힌 통로를 "통과"로 판정하는 false negative 발생.

**확정**: `scale_mm_per_px`가 파이프라인에 이미 존재하므로, 허용 오차를 mm 단위로 직접 지정하면 세그먼트 수 공식 불필요.

```python
# 이미지/PDF (OpenCV)
# sagitta_max = 1mm → 픽셀 단위로 변환해서 approxPolyDP epsilon으로 사용
epsilon_px = 1.0 / scale_mm_per_px
cv2.approxPolyDP(contour, epsilon=epsilon_px, closed=True)

# DXF (ezdxf) — 애초에 mm 단위
arc.flattened(sagitta=1.0)  # 1mm 오차 보장
```

**근거**: sagitta(호-현 최대 거리) 1mm = 시공 허용 오차(±3mm) 이내. buffer(450) 판정 뒤집힘 없음.

---

## Issue 19. Main Artery — 비상 탈출 경로 사전 캐싱 + 검증 이원화

**문제**: 1200mm 비상 대피로 기준이 배치 루프 내에서 체크되지 않고 최종 검증 모듈에서만 처리됨. 배치 완료 후 마지막 단계에서 1200mm 실패 시 전체 배치 무효화.

**확정**: Agent 2 후반부 NetworkX 완료 직후 Main Artery 사전 계산 + 캐싱. 루프 내 검증 이원화.

**Main Artery 계산 (Step 5-b)**:
```python
# 복수 입구: super-source 노드 기준 최단 경로 사용
# 비상구가 별도 있으면 entrance → emergency_exit
# 단일 입구: entrance → 가장 먼 노드 (최장 대피 경로 보호)
emergency_target = emergency_exit_node if emergency_exit_node else farthest_node
artery_nodes = nx.shortest_path(G, entrance_node, emergency_target, weight="weight")
space_data["fire"]["main_artery"] = LineString([node_coords[n] for n in artery_nodes])
```

**루프 내 검증 이원화**:
```python
# 1) Main Artery 체크 (1200mm) — 먼저 체크
if object_bbox.intersects(space_data["fire"]["main_artery"].buffer(600)):
    skip  # 비상 탈출 경로 침범

# 2) 일반 통로 체크 (900mm) — 기존 buffer(450)
```

**캐시 생명주기**:
- `main_artery`: 도면 구조 기반 → **Global Reset 후에도 파기하지 않음** (오브젝트 배치와 무관)
- `static_buffered_obstacles`: 기존대로 Global Reset 시 파기

**효과**: 1200mm 비상 경로는 배치 중 proactive 보호 → 최종 검증에서 1200mm로 뒤집힐 일 없음.

---

## Issue 20. 조합형 기물 연속 배치 + Z-fighting 방어

### 1. 충돌 판정식 교체

**문제**: `intersects()`는 접면도 충돌로 잡음. `overlaps()`는 한 물체가 다른 물체에 완전히 포함될 때 False — 두 가지 모두 부적합.

**확정**: `intersection(placed).area > 0` — 실제 면적 교차가 있을 때만 충돌 판정.

```python
# 일반 오브젝트 충돌 체크
if obj_polygon.intersection(placed_polygon).area > 0:
    skip  # 실제 면적 겹침만 거절. 접면(touches)은 허용.

# Dead Zone만 예외 — 접면도 허용 불가
if obj_polygon.intersects(dead_zone):
    skip
```

### 2. DB 스키마 추가 + 좌표 보정

`furniture_standards` 테이블에 연속 배치 필드 추가:

```sql
can_join         BOOLEAN  DEFAULT false  -- 연속 배치 허용 여부
overlap_margin_mm INTEGER DEFAULT 0     -- 파고드는 마진 (mm)
```

`can_join=True` 오브젝트 쌍은:
1. `calculate_position` 내 `object_gap_mm`을 0으로 우회
2. 중심점을 `overlap_margin_mm`만큼 상대 오브젝트 방향으로 이동 (역산)
3. **충돌 체크 스킵** — `intersection(placed).area > 0`에서 잡히므로 can_join 쌍끼리는 체크 제외

```python
# join_with 필드가 있는 쌍에만 예외 적용 (Option A — LLM이 명시적으로 지정)
if placement.join_with and placement.join_with == existing.object_type:
    pass  # 충돌 체크 스킵, object_gap_mm=0, overlap_margin_mm 역산 적용
    # can_join=False 오브젝트에 join_with 설정 시 Pydantic 검증 실패
else:
    if obj_polygon.intersection(placed_polygon).area > 0:
        skip
```

### 3. Three.js Z-fighting 방어

0mm 접면 또는 overlap_margin_mm 파고들기 시 Three.js Z-fighting 발생. .glb 원본 데이터 및 좌표는 변경하지 않음.

프론트엔드 머티리얼 전역 적용:
```javascript
material.polygonOffset = true;
material.polygonOffsetFactor = 1;
material.polygonOffsetUnits = 1;
```

> .glb 내보내기용 원본 geometry/좌표 불변 유지. 렌더링 레이어에서만 Z-buffer 처리.

---

## Issue 21. inward/center direction 오브젝트 회전 규칙

**문제**: inward/center direction에서 오브젝트의 width/depth 중 어느 축이 이동 방향(entrance ↔ floor center)과 수직인지 미정.

**확정**: **Option A — Width Perpendicular**

width가 이동 방향에 수직(좌우로 펼쳐짐), depth가 이동 방향과 평행(앞뒤로 배치).

```
입구에서 걸어들어오는 방향 →

  ←── width(1200) ──→
  ┌────────────────┐
  │                │  depth(400)
  └────────────────┘
       [오브젝트]
```

사람이 입구에서 걸어들어오면 오브젝트 정면(width 방향)이 보임. depth는 이동 방향과 평행해 통로 점유를 최소화.

- Option B (Depth Perpendicular) 기각: 오브젝트를 옆으로 세운 형태 — 실제 팝업 배치에서 의도적 케이스 없음.
- `wall_facing`과 동일한 정면 방향 원칙을 inward/center에도 적용.

**코드 적용**:
```python
# inward / center direction
rotation_angle = angle_to_entrance  # entrance 방향을 바라보는 각도
# width축이 이 각도에 수직, depth축이 평행
bbox = rotated_rectangle(center, width, depth, rotation_angle)
```

---

## Issue 22. 도면 타입 분리 — 파서 구조 확장

**문제**: 현재 `FloorPlanParser`는 파일 형식(DXF/PDF/이미지)만 구분. 도면 종류(평면도/단면도/입면도) 구분 없음. 단면도에서 `ceiling_height_mm` 추출 불가.

**추가 배경**: 단면도 없이는 기물 높이 검증(`object.height_mm > ceiling_height_mm`) 불가 → Z축 데이터 신뢰성 보장 안 됨.

**확정 구조**:

```
DrawingParser (파일 형식 어댑터 유지)
  → 도면 타입 자동 감지 (평면도 / 단면도 / 입면도)
  → 단일 파일 내 복수 도면 분리 (DXF 레이아웃, PDF 페이지)
  → 복수 파일 각각 처리
  → ParsedDrawings 통합 스키마로 출력
```

**받는 도면 타입 (현재)**:
- 평면도: floor polygon, 벽, 입구, 설비 위치
- 단면도: ceiling_height_mm, wall_height_mm

**향후 추가 가능 (현재 미구현)**:
- 천장도, 입면도, 상세도 — 인식률 향상 목적 아님. 별도 기능 필요 시 추가.

**출력 스키마**:
```python
class ParsedSection:
    ceiling_height_mm: float
    confidence: str   # "high" / "medium" / "low"
    source: str       # "dxf_dimension" / "ocr" / "vision" / "user_input"

class ParsedDrawings:
    floor_plan: ParsedFloorPlan        # 기존 유지
    section: Optional[ParsedSection]   # 단면도 없으면 None → 사용자 입력 fallback
```

**도면 타입 감지 — 어댑터 내부에서 처리**:
| 형식 | 감지 방법 |
|------|-----------|
| DXF | 레이아웃 이름 ("단면", "SECTION", "S-") / 레이어명 |
| PDF | 타이틀 블록 OCR ("단면도", "S-1") |
| 이미지 | Claude Vision — 도면 종류 판단 |

**단면도 없을 때 fallback**:
```python
if parsed_drawings.section is None:
    ceiling_height_mm = user_input or 3000  # 기본값 3000mm
    space_data["floor"]["ceiling_height_mm"] = {
        "value": ceiling_height_mm, "confidence": "low", "source": "default"
    }
```

**`ParsedFloorPlan` → `ParsedDrawings` 스키마 교체** (영향 범위: floorplan_detection.md, agent-2-floorplan.md)

---

## 미결 사항

| 항목 | 내용 |
|---|---|
| step_mm ratio | sqrt(w²+d²) × ratio 의 ratio 수치 — 실제 도면 테스트 후 결정 |
| 소형/대형 공간 기준선 | usable_area_sqm 기준 분기 수치 — 실제 도면 테스트 후 결정 |
| inward/center 오프셋 규칙 | Issue 17 Hybrid Sampling으로 해소 — 격자점 = 오브젝트 중심, 별도 오프셋 없음 |
| inward/center 회전 규칙 | Issue 21 확정 — Width Perpendicular (A안) |
| 비정형 공간 zone 임계값 | walk_mm 기반 zone 구분의 임계값 수치 — 실제 도면 테스트 후 결정 |
| 내부 벽/방 구분 | Issue 17 확정 |
| 곡선 벽 근사 오차 | Issue 18 확정 (sagitta ≤ 1mm) |
| OCR 스케일 오차 | DXF 입력은 ezdxf mm 직접 추출로 우회. PDF/이미지는 알려진 한계 — 치수 직접 입력 fallback으로 대응. PoC 실측 필요. |

---

## 의도적으로 수용한 설계 한계

**Greedy 순차 배치 (priority 순 탐색)**

현재 배치 루프는 Agent 3의 priority 순서대로 오브젝트를 하나씩 확정합니다. "낮은 우선순위 오브젝트를 특정 위치에 먼저 배치해야 높은 우선순위 오브젝트들이 들어가는" 기하학적 최적해를 보장하지 않습니다.

**의도적으로 수용한 이유**: 팝업 스토어 규모(30~60m²)에서 완전 탐색(Backtracking) 또는 CSP 솔버는 비용 대비 효과가 없습니다. 배치 품질보다 응답 속도와 브랜드 기획 의도 반영이 우선입니다. 최적해 미보장은 알려진 한계이며, Deterministic Fallback(Issue 15)이 최악의 경우를 방어합니다.


