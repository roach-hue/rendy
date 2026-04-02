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

# LandingUp 아키텍처 의사결정 기록
작성일: 2026-04-01

---

## Issue 1. Agent 1 — LLM 환각으로 인한 수치 오류

**문제**: PDF에서 400mm를 4000mm로 잘못 읽어도 값 범위(300~5000) validator 통과 가능

| 선택지 | 내용 | 결과 |
|---|---|---|
| A | 사용자 확인 UI에서 사람이 시각으로 잡음 | 기각 — fallback이지 시스템 해결책 아님 |
| B | Regex 전처리 hybrid (텍스트 PDF는 Regex로 수치 추출, LLM은 라벨링만) | **채택** |

**결정**: 텍스트 PDF → Regex 기계 추출 → LLM 라벨링. 이미지 PDF → Claude Vision 유지.

---

## Issue 2. step_mm / max_steps 기준

**문제**: attempt_placement가 위치 조정 시 이동 보폭과 최대 시도 횟수 기준 없음

| 선택지 | 내용 | 결과 |
|---|---|---|
| A | 50~100mm, 10회 이하 하드코딩 (Gemini 원안) | 기각 — 공간 크기 무관하게 고정값은 부적합 |
| B | space_data 기반 동적 계산 (bbox_w 비율, zone 반경 기준) | **채택** |

**결정**: step_mm = bbox_w × 비율 (비율 수치 미결). max_steps = zone 반경 / step_mm. attempt_placement 목적은 미세 회피이므로 zone 반경 초과 시 즉시 실패 선언.

---

## Issue 3. Cascade Failure 처리

**문제**: 상위 오브젝트가 유일한 통로를 선점하면 하위 오브젝트 배치 불가. Greedy 구조적 한계.

| 선택지 | 내용 | 결과 |
|---|---|---|
| A | placed_objects 유지 + alternative_references 풀 확장 | 기각 — 근본 원인(상위 선점) 해결 불가 |
| B | Targeted Removal: 원인 오브젝트만 제거 | 기각 — NetworkX는 결과(막힘)만 반환, 원인 역추적 불가 |
| C | Global Reset + 실패 컨텍스트 주입 후 Agent 3 재호출 | **채택** |

**결정**: 배치 실패 시 도면 전체 초기화. Agent 3 재호출 시 "A+B 조합이 통로를 막았다"는 실패 맥락 포함. 단, 동일 reasoning 반복 → 무한루프 가능성 미해결.

---

## Issue 4. 사전 분석 레이어 (Pre-analysis Layer)

**문제**: Agent 3이 미래 배치를 고려하지 않고 현재 최선만 판단하는 Greedy 한계 보완 목적으로 제안

| 선택지 | 내용 | 결과 |
|---|---|---|
| A | Agent 3 이전에 충돌 가능성 분석 레이어 추가, 자연어로 경고 주입 | **기각** |
| B | 없음 | 유지 |

**기각 이유**: 정확한 사전 분석 = 본 배치 연산과 동일한 Shapely+NetworkX 시뮬레이션 필요 (낭비). 가벼운 근사치(면적 합산)는 병목 구간 미감지 → LLM에 거짓 정보 주입. 자연어 조건문 증가 → 환각 확률 상승.

---

## Issue 5. 공간 물리적 한계 처리 (Graceful Degradation)

**문제**: 공간이 모든 오브젝트를 수용 불가한 경우 처리 로직 없음 (기존 설계 맹점)

| 선택지 | 내용 | 결과 |
|---|---|---|
| A | 없음 (기존) | 기각 |
| B | Auto-drop: 2회 Global Reset 후에도 실패 시 최하위 priority 오브젝트 드랍, 나머지로 재시도, 리포트에 명시 | **채택** |

**결정**: 물리적 한계 판정 후 priority 기반 자동 드랍. 최종 리포트에 "배치 불가 오브젝트 목록 + 사유" 포함. Cascade Failure(배치 순서 문제)와는 별개 케이스.

---

---

## Issue 6. calculate_position 함수 스펙

> ⚠️ **SUPERSEDED**: wall 표현 방식이 Issue 8에서 LineString으로 교체됨. `wall_surface_y` 단일 좌표 방식 폐기. **Issue 8을 기준으로 구현할 것.**

**확정된 구조 (Issue 8 교체 전 기록 보존용)**:
- `calculate_position`은 명시적 함수로 분리
- 모서리 4개는 함수 내부에서 중심점 + width/2, depth/2 조합으로 계산 후 Shapely polygon 생성
- 코드 순회 루프 안에서 reference_point마다 실행

**direction별 중심점 계산 — 미결 사항 포함**:

| direction | 중심점 계산 | 회전각 | 상태 |
|---|---|---|---|
| wall_facing | Issue 8 (LineString + 수선의 발)으로 교체 | wall_normal 반대 방향 | Issue 8 참조 |
| inward | reference_point에서 entrance 방향으로 오프셋 필요 — 규칙 미결 | entrance 좌표를 향하는 각도 | **미결** |
| outward | 더미 처리 — 실제 사용 케이스 없음. 추후 케이스 확인 시 추가 | — | **비활성** |
| center | reference_point에서 floor center 방향으로 오프셋 필요 — 규칙 미결 | floor center 좌표를 향하는 각도 | **미결** |

**⚠️ 오류 수정**: inward/center 중심점을 `reference_point.x, reference_point.y` 그대로 쓰면 오브젝트가 벽 안으로 파고들 수 있음. 방향별 오프셋 규칙 필요.

**outward 더미 처리 이유**: 캐릭터/조형물은 inward, 선반/가벽은 wall_facing, 포토존은 center로 커버됨. outward가 필요한 실제 오브젝트 케이스 없음.

---

---

## Issue 7. Global Reset 무한루프 + Agent 3 재호출 최소화

**문제**: cascade failure 시 Agent 3 재호출이 반복되면 API 비용 + 지연 + 무한루프 위험

**확정된 구조**:

Agent 3 역할 분리:
- 기획 결정만 담당 (zone_label만 출력 — reference_point 출력 금지)
- 위치 탐색은 코드가 전담

Agent 3 output 스키마 (zone_label 통일):
- 소형/대형 구분 없이 Agent 3은 항상 zone_label만 뱉음
- 소형 공간은 zone당 reference_point 1개라 결과 동일
- Union 타입 채택 안 함 — target_type 오태깅 버그 위험

공간 크기 기준 분기 (`space_data["floor"]["usable_area_sqm"]`):
- 코드가 zone 안 reference_point 전체 순회 (소형/대형 공통)
- 기준선 수치는 실제 도면 테스트 후 결정

물리적 한계 vs cascade failure 구분:
```
reference_point 전체 순회 전부 실패
→ 단독 배치 테스트 (빈 도면에 해당 오브젝트만)
  → 단독 실패 = 물리적 한계 → Graceful Degradation
  → 단독 성공 = cascade failure → Global Reset + Agent 3 재호출
```

placed_because 처리:
- Agent 3 기획 의도 보존
- 코드가 위치 조정한 경우: "1차 지정 위치(X) 공간 부족으로 인접 구역(Y) 자동 조정" 한 줄 추가

---

---

## Issue 8. 벽면 추상화 — LineString + 수선의 발

**문제**: wall_surface_y 단일 좌표는 수직/수평 벽 전제. 사선/곡선 벽에서 calculate_position이 틀린 좌표 산출.

**확정**:
- 벽을 LineString 객체로 저장 (시작점 + 끝점)
- calculate_position의 wall_facing 연산 시 Shapely `LineString.project()` + `interpolate()`로 수선의 발 계산
- 오브젝트 중심점 → wall_linestring 수선 교점 → depth/2 만큼 법선 벡터 방향으로 평행 이동

```python
# Agent 2 후반부 저장
space_data["north_wall_mid"]["wall_linestring"] = LineString([(0,4000),(6000,4000)])

# calculate_position wall_facing 연산
foot = wall_linestring.interpolate(wall_linestring.project(Point(ref_x, ref_y)))
# foot에서 법선 방향으로 depth/2 이동 → 오브젝트 중심점
```

---

## Issue 9. step_mm 공식 확정

**문제**: bbox_w만 기준으로 삼으면 얇고 긴 오브젝트(w=100, d=2000)에서 step이 극단적으로 작아짐.

**확정**:
```
step_mm = sqrt(w² + d²) × ratio
```
- 오브젝트 실제 점유 크기(대각선)에 비례하는 일관된 보폭
- ratio 초기값 미결 — 실제 도면 테스트 후 결정

---

## Issue 10. zone 경계 — Shapely Polygon + contains 선행 검사

**문제**: zone이 점의 집합이면 코드 탐색 중 인접 zone으로 이탈 가능.

**확정**:
- Agent 2 후반부에서 zone을 Shapely Polygon으로 저장
- Voronoi Diagram 채택 안 함 — 벽/Dead Zone으로 자연 구획되므로 정적 분할로 충분

```python
space_data["mid_zone"]["boundary"] = Polygon([(x1,y1),(x2,y2),...])
```

- attempt_placement 탐색 시 충돌 검사 이전에 contains 선행 체크
```python
if not zone_polygon.contains(object_bbox):
    continue  # zone 이탈 → 즉시 다음 좌표
```

---

---

## Issue 11. NetworkX 과부하 — buffer 근사 검증 도입

**문제**: step_mm 이동마다 NetworkX 전체 재연산 → 서버 다운

**확정**:
- 미세 조정 루프 안: Shapely buffer(450) 근사 검증만 사용
- 오브젝트 확정 시: NetworkX 최종 1회 교차 검증

**buffer 근사 원리**:
- 장애물 + 벽에 buffer(450) 적용 → 팽창된 장애물이 서로 맞닿으면 900mm 통로 막힘 판정
- 보수적 근사 → false positive 가능 (실제 통과 가능한데 막혔다고 판정)
- false positive는 attempt_placement 루프 몇 번 더 도는 비용만 발생
- false negative(통로 막혔는데 통과 판정)보다 압도적으로 안전한 trade-off

**필수 로직 A — 가상 입구 선분 (Virtual Entrance Line)**:
- 입구는 점이 아니라 선분 (예: 2000mm 개구부)
- 단일 점 451mm 이동 방식 폐기
- Shapely `offset_curve`로 입구 선분 전체를 벽 법선 방향으로 (450 + 10)mm 평행 이동
- 가상 입구 선분이 팽창된 장애물에 1mm라도 노출되면 출발 가능(True) 판정

**필수 로직 B — 캐시 생명주기 (Cache Lifecycle)**:
- 확정된 기물 + 벽면 buffer 병합본 1회 캐싱 → 루프 안에서 임시 오브젝트만 추가 체크
- Global Reset 발생 시 (`placed_objects.clear()` 즉시) `static_buffered_obstacles` 캐시 동시 파기
- 재진입 시 고정 벽체 데이터만으로 캐시 재계산

---

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

**선택지**:

| 방식 | 내용 | 상태 |
|---|---|---|
| A | Agent 1이 자연어 → 수치 변환 (예: 최소 이격거리 mm). Shapely가 거리 검증 | 대기 — 수치 변환이 억지스러울 수 있음 |
| B | 배치 후 LLM이 두 오브젝트 간 거리 요약 받아서 규정 준수 여부 판단 | 대기 — LLM 추가 호출 비용 발생 |
| **C** | **배치 확정 후 코드가 관계 제약 오브젝트 쌍의 zone_label 비교. 같은 zone이면 위반 → Agent 3 재호출** | **채택** |

**확정 (C)**:
```python
if lion["zone_label"] == chun["zone_label"]:
    → 관계 제약 위반 → Agent 3 재호출
```
- 수치 불필요, LLM 추가 호출 불필요, zone_label 비교만으로 검증
- C 실패 시 A → B 순서로 시도

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

**해결 방향 — convex decomposition**:

오목형(concave) polygon을 볼록형(convex) 하위 영역으로 분할하는 computational geometry 정립 알고리즘.

```
ㄱ: 오목 꼭짓점 1개 → 2개 볼록 영역
ㄷ: 오목 꼭짓점 2개 → 3개 볼록 영역
임의 형태: 오목 꼭짓점 N개 → N+1개 볼록 영역
```

- 형태(ㄱ/ㄷ/T 등)와 무관하게 적용 가능
- 분할된 각 볼록 영역 = 1개 zone
- 각 zone 안에서 기존 격자 순회 + reference_point 생성 동일하게 작동

**미결**:
- 분할 알고리즘 선택 (Hertel-Mehlhorn 등) — 구현 단계에서 결정
- 분할된 zone에 zone_label을 어떻게 자동 부여할지 (벽면 방향 기반? 입구 거리 기반?)
- Shapely 내장 기능으로 가능한지 vs 외부 라이브러리 필요 여부

---

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

**미결**: 전체 아키텍처 수준의 결정 필요. 단순 미결이 아니라 Agent 2 전반부(감지) + 후반부(계산) + 검증 모듈 전부에 영향.

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

**미결**:
- 세그먼트 수 하한 결정 (최대 오차를 시공 허용 오차 이내로 보장)
- 곡선 반지름에 따른 동적 세그먼트 수 계산 공식
- 또는 Shapely의 `buffer(..., resolution=N)` 등 원호 처리 기능 활용 가능성 검토

---

## 미결 사항

| 항목 | 내용 |
|---|---|
| step_mm ratio | sqrt(w²+d²) × ratio 의 ratio 수치 — 실제 도면 테스트 후 결정 |
| 소형/대형 공간 기준선 | usable_area_sqm 기준 분기 수치 — 실제 도면 테스트 후 결정 |
| inward 오프셋 규칙 | reference_point에서 entrance 방향으로 얼마나 띄울지 — 실제 오브젝트 크기 확인 후 결정 |
| center 오프셋 규칙 | reference_point에서 floor center 방향으로 얼마나 띄울지 — 실제 오브젝트 크기 확인 후 결정 |
| 비정형 공간 zone 분할 | convex decomposition 알고리즘 선택 + zone_label 자동 부여 규칙 — 구현 단계에서 결정 |
| 내부 벽/방 구분 | 배치 가능 영역 추출 규칙 + 복수 입구 처리 — 아키텍처 수준 결정 필요 |
| 곡선 벽 근사 오차 | 세그먼트 수 하한 또는 동적 계산 공식 — 법적 기준(소방) 오차 허용 불가 전제로 결정 |


