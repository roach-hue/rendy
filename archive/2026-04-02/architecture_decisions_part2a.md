# Architecture Decisions — Part 2a (Issue 12-16)

> Part 1: architecture_decisions_part1.md | Part 2b: architecture_decisions_part2b.md

# Architecture Decisions — Part 2 (Issue 12-22 + 미결)

> Part 1: architecture_decisions_part1.md (Issue 1-11)

## Issue 12. Agent 3 재호출 — 프롬프트 경량화 전처리 모듈

**문제**: placed_objects 전체 JSON 누적 → 토큰 폭증 + LLM 망각

**기각된 대안**:
- 반경 3000mm 고정값: 공간 크기 무관 → 무고한 기물 원인 지목 가능
- 동적 반경 sqrt(usable_area_sqm) × 계수: 여전히 원형 범위 내 모든 기물 수집 → false context 위험

**확정 — Choke Point intersects 방식**:

```
buffer(450)으로 장애물 팽창
→ 팽창된 장애물들이 서로 맞닿은 지점 = Choke Point (통로 막힌 구간) 추출
→ Choke Point polygon과 placed_objects 기물 Bounding Box를 1:1 intersects() 체크
→ 실제로 걸쳐있는 기물만 원인(Culprit)으로 추출
→ f-string 템플릿으로 기계적 조립
→ Agent 3에 요약문만 전달
```

```python
f"배치 실패. {exact_culprit_name}이(가) 통로를 물리적으로 차단함."
```

**왜 이 방식인가**:
- 거리 기반 탐색 완전 폐기 → 교차 기반 탐색으로 전환
- 도면 크기(6000mm든 10000mm든) 무관하게 동일하게 작동
- 실제로 막힌 지점에 걸쳐있는 기물만 100% 수학적으로 추출
- LLM이 요약문을 생성하는 게 아니라 읽기만 함 → 수치 환각 원천 차단

**피드백 전체 흐름**:
```
에러 감지: buffer(450) 팽창 후 가상 입구 ~ 목적지 경로 차단 확인
    ↓
Choke Point 추출: 팽창된 장애물들이 맞닿은 구간 polygon 계산
    ↓
원인 색출: Choke Point.intersects(기물 bbox) → 진짜 범인만 추출
    ↓
기계적 조립: f-string 템플릿으로 요약문 생성
    ↓
단방향 주입: 요약문만 Agent 3 재호출 프롬프트로 전달
```

---

## Issue 13. zone polygon 내부 순회 패턴

**문제**: polygon은 무한한 점의 집합 — 탐색 시작점과 방향 규칙 없으면 랜덤 탐색 또는 무한루프

**확정**:
```
zone_polygon bounding box 안에 step_mm 격자점 생성
→ zone_polygon.contains(point) 로 유효한 점만 추림
→ wall_linestring 기준 거리 오름차순 정렬
→ 순서대로 시도
```
- wall_facing 의도와 일치 (벽에 가장 가까운 점부터)
- **격자점 0개 fallback**: step_mm이 zone 크기보다 커서 격자점이 0개 생성될 경우 zone polygon 중앙점 + 양 끝점 총 3개를 fallback으로 사용

---

## Issue 14. 관계 제약 검증

**문제**: "라이언과 춘식이를 떨어뜨릴 것" 같은 자연어 관계 제약을 Agent 3이 placed_because에 언급해도 실제로 지켰는지 코드가 검증하지 않음

**C안 기각 (논리적 오류)**:
- 같은 zone 내 10m 간격 → 위반 판정 (false positive)
- zone 경계 1cm 간격 → 통과 판정 (false negative)
- zone_label 비교는 물리적 거리를 보장하지 않음

**확정 — Shapely distance + clearspace_mm**:

```python
# space_data["brand"]["clearspace_mm"]["value"] 를 threshold로 사용
if Shapely.distance(lion_bbox, chun_bbox) < space_data["brand"]["clearspace_mm"]["value"]:
    # 관계 제약 위반 → Agent 3 재호출
```

- `clearspace_mm`가 브랜드 메뉴얼에 없는 경우 → DEFAULTS 적용, `source: "default"` 기록
- LLM 추가 호출 불필요, 물리적 거리 기반 코드 검증
- false positive / false negative 모두 제거

---

## Issue 15. Agent 3 재호출 최종 fallback — deterministic 강제 배치

**문제**: Issue 3(cascade → Global Reset), Issue 5(물리적 한계 → Graceful Degradation), Issue 7(zone 소진 → 자연 종료)이 각각 다른 실패 케이스를 처리하지만, 그 사이에 틈이 있음.

```
케이스 A: 단독 배치 실패        → Issue 5 (Graceful Degradation) ✅
케이스 B: cascade failure       → Issue 3 (Global Reset + 재호출) ✅
케이스 C: zone 전부 소진        → Issue 7 (자연 종료) ✅
케이스 D: zone은 남아있지만 Agent 3이
          계속 같은 나쁜 zone만 고름  → ❌ 처리 없음
```

**케이스 D 시나리오**: Agent 3이 Choke Point 피드백을 받아도 동일한 zone을 재선택하거나, 남은 zone 중 어디에 넣어도 cascade가 반복. zone이 남아있으니 자연 종료 조건 미충족. Global Reset만 반복.

| 선택지 | 내용 | 결과 |
|---|---|---|
| A | Global Reset 무제한 허용 (기존) | 기각 — 무한루프 + 비용 폭발 |
| B | Global Reset 횟수 제한 + 초과 시 파이프라인 중단 | 기각 — 사용자에게 "실패했습니다"만 보여주면 서비스 불가 |
| C | **Global Reset 최대 N회 + 초과 시 deterministic fallback 계층** | **채택** |

**확정 (C) — 3단계 fallback**:

```
1단계: 정상 흐름
  Agent 3 기획 → 코드 순회 → 배치 시도

2단계: Global Reset (최대 2회)
  cascade 감지 → Choke Point 피드백 → Agent 3 재호출
  Agent 3은 실패 종관 + 남은 zone 정보를 받아 재기획

3단계: deterministic fallback (Global Reset 2회 소진 후)
  LLM 개입 중단. 코드가 아래 규칙으로 강제 배치:
  ① priority 높은 오브젝트부터 순서대로
  ② zone 제약 무시 — 전체 floor polygon에서 탐색
  ③ entrance blocking 절대 금지 (입구 앞 배치 차단)
  ④ 배치 가능한 위치 중 벽 최인접 선택
  ⑤ 그래도 불가 → Graceful Degradation (드랍)
```

**왜 이 문제가 반복 출현하는가**:
- Issue 3에서 "무한루프 가능성 미해결" 명시 → Issue 7에서 "zone 소진 = 자연 종료"로 대응 → 근데 zone 미소진 + 반복 실패 케이스가 여전히 틈
- 근본 원인: Global Reset은 "LLM이 더 나은 판단을 해줄 것"이라는 전제에 의존. LLM이 같은 판단을 반복하면 무한루프
- **해결 본질**: 일정 횟수 이후 LLM 의존을 끊고 코드가 결정권을 가져감

**deterministic fallback의 품질은 정상 흐름보다 낮지만, "시스템이 반드시 결과물을 내는 것"이 "기획 의도에 맞는 배치를 찾는 것"보다 우선**이다.

**리포트 표기**: deterministic fallback으로 배치된 오브젝트는 `source: "fallback"` 표기. "Agent 3 기획이 아닌 자동 배치" 명시.

---

## Issue 16. 비정형 공간(ㄱ/ㄷ) zone 분할

**문제**: Issue 10에서 "벽/Dead Zone으로 자연 구획되므로 정적 분할로 충분"이라고 했지만, 이 규칙은 직사각형 공간 전제. 비정형(오목형) 공간에서 zone을 어떻게 나누는지 정의 없음.

```
직사각형 — 벽 4면 기준으로 자르면 자명

ㄱ자 (L-shape):
┌────────────┐
│            │
│            │        ← 꺾이는 지점에서 어떻게 나누는가?
│     ┌──────┘
│     │
└─────┘

ㄷ자 (U-shape):
┌──┐      ┌──┐
│  │      │  │       ← 오목 꼭짓점 2개. 분할 영역 3개.
│  │      │  │
│  └──────┘  │
│            │
└────────────┘
```

**기각된 방향 — convex decomposition**:

오목형 polygon을 볼록형 하위 영역으로 물리적으로 분할하는 방식.

**기각 이유**: 분할선(seam) 위에 걸쳐야 맞는 오브젝트가 `zone_polygon.contains()` 체크에서 실패 → fragmentation 데드락 유발. 외부 라이브러리(polypartition 등) 의존성 증가.

---

**확정 — NetworkX walk_mm 기반 zone 정의**:

공간을 물리적으로 자르지 않는다. Agent 2 후반부에서 NetworkX가 이미 계산하는 보행거리(walk_mm)를 임계값으로 zone을 구분한다.

```python
# Agent 2 후반부 — 격자점마다 walk_mm 저장
for point in grid_points:
    space_data[point.key]["walk_mm"] = nx.shortest_path_length(G, entrance_node, point_node)

# zone 임계값 (실제 수치는 도면 테스트 후 결정)
space_data["zones"] = {
    "entrance_zone": {"walk_mm_max": 400},
    "mid_zone":      {"walk_mm_min": 400, "walk_mm_max": 700},
    "deep_zone":     {"walk_mm_min": 700},
}

# placement_slot zone_label 자동 부여
for slot in placement_slots:
    slot["zone_label"] = assign_zone_by_walk_mm(slot["walk_mm"], space_data["zones"])
```

**코드 순회 루프 변경**:
```python
# 기존: zone_polygon.contains(point) 체크
# 변경: walk_mm 임계값 필터
candidates = [p for p in grid_points
              if zone_thresholds[zone_label]["min"] <= p["walk_mm"] <= zone_thresholds[zone_label]["max"]]
```

**장점**:
- 공간 형태(ㄱ/ㄷ/T) 무관하게 자동 대응 — floor_polygon 전체가 연속 공간으로 유지
- fragmentation 없음 — 경계선이 물리적으로 존재하지 않음
- NetworkX는 이미 Agent 2 후반부에 있음 — 추가 라이브러리 불필요
- zone_label → Agent 3 인터페이스 변경 없음

**미결**:
- walk_mm 임계값 수치 (entrance_zone 상한, mid_zone 상/하한) — 실제 도면 테스트 후 결정

---

