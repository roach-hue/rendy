---
name: 배치 기획 스킬
description: Agent 3이 배치 기획 후 코드 순회 루프가 실제 좌표를 계산하고 검증하는 전체 배치 프레임워크
---

# 배치 기획 스킬 (Placement Planning Skill)

## 목적
Agent 3의 배치 기획(zone_label + direction)을 실제 좌표로 변환하고, Shapely/NetworkX로 검증하는 전체 배치 루프.

---

## Agent 3 — 배치 기획 [LLM]

### Input
- zone_label 자연어 요약만 ("north_wall_mid: mid_zone, shelf 3개 수용 가능")
- eligible_objects 목록
- 관계 제약 자연어
- 허용 zone_label 목록
- 실패 컨텍스트 (재호출 시)

### Output (Pydantic 강제)
```python
class Placement(BaseModel):
    object_type: str
    zone_label: Literal["entrance_zone", "mid_zone", "deep_zone"]  # placement_slot 출력 금지, 존재하지 않는 zone 차단
    direction: Literal["wall_facing", "inward", "center"]
    priority: int
    placed_because: str          # Agent 3 기획 의도 서사 — 레퍼런스 이미지 참조 허용, mm값 출력 금지
    adjustment_log: Optional[str] = None  # 코드 전용 — 위치 조정 발생 시 코드가 채움, Agent 3 출력 금지
    join_with: Optional[str] = None  # 연속 배치 대상 object_type (Issue 20 — can_join 쌍에만 사용)
```

### 제약
- 좌표·mm값 출력 절대 금지
- outward direction은 더미 처리 — 실제 사용 케이스 없음 (architecture_decisions.md Issue 6)
- Circuit Breaker: Pydantic 실패 → 재시도 최대 3회 → 파이프라인 중단

---

## calculate_position [코드]

Agent 3의 zone_label + direction → 실제 polygon 좌표 계산.
코드 순회 루프 안에서 placement_slot마다 실행.

### direction별 계산

**wall_facing** (Issue 8 — LineString + 수선의 발):
```python
# Shapely LineString + 수선의 발
foot = wall_linestring.interpolate(wall_linestring.project(Point(ref_x, ref_y)))
# foot에서 wall_normal 반대 방향으로 depth/2 이동 → 오브젝트 중심점
```

**inward**: 격자점 = 오브젝트 중심 (Issue 17 Hybrid Sampling으로 오프셋 불필요)
- 회전: width가 이동 방향에 수직, depth가 평행 (Issue 21 — Width Perpendicular)

**center**: 격자점 = 오브젝트 중심 (Issue 17 Hybrid Sampling으로 오프셋 불필요)
- 회전: width가 floor center 방향에 수직, depth가 평행 (Issue 21 — Width Perpendicular)

**outward**: 더미 처리 (실제 케이스 없음)

**모서리 계산**: 중심점 + width/2, depth/2 조합으로 Shapely polygon 생성

---

## 코드 순회 루프

오브젝트 1개 단위 흐름:

```
Agent 3: zone_label 지정
    ↓
zone 안의 placement_slot 전체 순회
    └→ calculate_position
    └→ Shapely 충돌 체크 — intersection(placed).area > 0 (면적 교차만 거절, 접면 허용 — Issue 20)
         can_join 쌍은 충돌 체크 스킵
         Dead Zone만 예외: intersects() 유지
    └→ buffer 이원화 검증 (Issue 19)
         ├→ 통과 → NetworkX 최종 1회 → 확정
         └→ 실패 → 다음 placement_slot
    ↓
전체 순회 전부 실패
    ↓
단독 배치 테스트 (빈 도면에 해당 오브젝트만)
    ├→ 단독 실패 = 물리적 한계 → Graceful Degradation
    └→ 단독 성공 = cascade failure → Global Reset → Agent 3 재호출
```

---

## 격자점 순회 패턴 (Issue 13, 17)

direction별로 탐색 방식을 분리 — Hybrid Sampling (Issue 17 하위 문제 4):

**wall_facing**:
```
wall_linestring 위를 step_mm 간격으로 1D 샘플링
→ 각 점에서 wall_normal 반대 방향으로 depth/2 이동 → 오브젝트 중심점 후보
→ 복도 폭 무관 — 좁은 복도에서도 항상 후보 생성
```

**inward / center**:
```
floor_polygon bounding box 안에 step_mm 격자점 생성
→ floor_polygon.contains(point) 로 유효한 점만 추림  # 공간 전체 — zone polygon 분할 없음
→ zone_label 기준 walk_mm 임계값으로 후보 필터링
→ wall_linestring 기준 거리 오름차순 정렬
→ 순서대로 시도
```

> zone polygon 경계(contains 체크) 방식 폐기. walk_mm 임계값 필터로 교체 (Issue 16)

**step_mm 공식** (Issue 9):
```
step_mm = sqrt(w² + d²) × ratio
```
- 오브젝트 실제 점유 크기(대각선)에 비례하는 일관된 보폭
- ratio 초기값 미결 — 실제 도면 테스트 후 결정

**격자점 0개 fallback** (Issue 13):
- step_mm이 zone 크기보다 커서 격자점이 0개 생성될 경우
- zone polygon 중앙점 + 양 끝점 총 3개를 fallback으로 사용

---

## buffer 이원화 검증 (Issue 11, 19)

> 루프 안에서 두 단계 체크. NetworkX는 확정 시 최종 1회만.

### 1단계: Main Artery 체크 (1200mm) — 먼저 실행

```python
# space_data["fire"]["main_artery"]는 Agent 2 후반부에서 캐싱된 불변 LineString
if object_bbox.intersects(space_data["fire"]["main_artery"].buffer(600)):
    skip  # 비상 탈출 경로 침범 — 즉시 거절
```

- main_artery 캐시는 Global Reset 후에도 유지 (도면 구조 기반, 오브젝트와 무관)

### 2단계: 일반 통로 체크 (900mm)

- 장애물 + 벽에 buffer(450) 적용 → 팽창된 장애물이 서로 맞닿으면 900mm 통로 막힘 판정
- 보수적 근사 → false positive 가능 (실제 통과 가능한데 막혔다고 판정)
- false positive는 루프 몇 번 더 도는 비용만 발생 — false negative보다 안전

**가상 입구 선분 (Virtual Entrance Line)**:
- 입구는 점이 아니라 선분 (예: 2000mm 개구부)
- Shapely `offset_curve`로 입구 선분 전체를 벽 법선 방향으로 (450+10)mm 평행 이동
- 가상 입구 선분이 팽창된 장애물에 1mm라도 노출되면 출발 가능(True) 판정

**캐시 생명주기**:
- `main_artery`: 불변 — Global Reset 후에도 파기하지 않음
- `static_buffered_obstacles` (확정 기물 + 벽면 buffer 병합본): Global Reset 시 즉시 파기

---

## cascade failure 처리 — Global Reset (Issue 3, 12)

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

**무한루프 종료**: 재호출 시 실패 zone 누적 전달 → Agent 3이 시도 가능한 zone 소진 시 자연 종료

---

## 물리적 한계 처리 — Graceful Degradation (Issue 5)

단독 배치 테스트 실패 시 물리적 한계 판정.

```
해당 오브젝트 drop
→ 나머지 오브젝트로 재시도
→ 최종 리포트: "배치 불가 오브젝트 목록 + 사유" 명시
```

---

## deterministic fallback — 최종 안전장치 (Issue 15)

> Global Reset 2회 소진 후에도 배치 실패가 반복되면 LLM 개입을 중단하고 코드가 강제 배치.

**왜 필요한가**: Global Reset은 "LLM이 더 나은 판단을 해줄 것"이라는 전제에 의존. LLM이 같은 zone을 반복 선택하면 zone이 남아있어도 무한루프.

**3단계 fallback 계층**:

```
1단계: 정상 흐름
  Agent 3 기획 → 코드 순회 → 배치 시도

2단계: Global Reset (최대 2회)
  cascade 감지 → Choke Point 피드백 → Agent 3 재호출

3단계: deterministic fallback (2회 소진 후)
  LLM 개입 중단. 코드가 강제 배치:
  ① priority 높은 오브젝트부터 순서대로
  ② zone 제약 무시 — 전체 floor polygon에서 탐색
  ③ entrance blocking 절대 금지
  ④ 배치 가능한 위치 중 벽 최인접 선택
  ⑤ 그래도 불가 → Graceful Degradation (드랍)
```

**리포트 표기**: deterministic fallback 배치 오브젝트는 `source: "fallback"` 표기. "Agent 3 기획이 아닌 자동 배치" 명시.

---

## zone_label 검증 (코드 2차 관문)

Agent 3이 출력한 zone_label을 해당 placement_slot의 실제 walk_mm 기반 zone과 대조.
Pydantic이 유효 이름을 보장하더라도, 이미지 참조 등으로 잘못된 zone을 고를 수 있음을 방어.

```python
actual_zone = assign_zone_by_walk_mm(space_data[slot_key]["walk_mm"], space_data["zones"])
if placement.zone_label != actual_zone:
    # Circuit Breaker 카운트 증가 → 재시도 또는 파이프라인 중단
    raise ZoneMismatchError(
        f"Agent 3 zone_label={placement.zone_label}, walk_mm 기준 실제 zone={actual_zone}"
    )
```

- 1차: Pydantic Literal → 존재하지 않는 zone 이름 차단
- 2차: walk_mm 대조 → 유효한 이름이지만 walk_mm 기준에 맞지 않는 경우 차단

---

## 관계 제약 검증 (Issue 14)

배치 확정 후 코드가 Shapely distance + clearspace_mm 비교:

```python
if Shapely.distance(lion_bbox, chun_bbox) < space_data["brand"]["clearspace_mm"]["value"]:
    # 관계 제약 위반 → Agent 3 재호출
```

- zone_label 비교 방식 기각 (false positive/negative 모두 발생 — Issue 14)
- clearspace_mm 없으면 DEFAULTS 적용 (`source: "default"`)

---

## placed_because / adjustment_log 분리

| 필드 | 작성 주체 | 허용 내용 | 금지 |
|------|-----------|-----------|------|
| `placed_because` | Agent 3 | 기획 의도 서사, 레퍼런스 이미지 브랜드 사례 | mm값, 좌표 |
| `adjustment_log` | 코드 | 위치 조정 사유 + 실제 거리(mm) | Agent 3 출력 |

```python
# 코드 조정 발생 시 — Agent 3 placed_because는 건드리지 않음
placement.adjustment_log = f"1차 지정 위치({original_slot}) 공간 부족으로 {actual_slot} 자동 조정 (거리: {dist_mm}mm)"
```

---

## 미결 사항 (실제 도면 테스트 후 결정)

| 항목 | 내용 |
|------|------|
| step_mm ratio | sqrt(w²+d²) × ratio의 ratio |
| 소형/대형 공간 기준선 | usable_area_sqm 분기 수치 |
