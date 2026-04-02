# 아키텍처 검토 세션 기록

> GPT 외부 분석 수신 시점(2026-04-01 17:46)부터 세션 종료까지

---

## 1. 발단 — GPT의 외부 분석

GPT가 rendy 아키텍처를 독자적으로 분석하여 2가지 핵심 제안을 보냄:

| # | GPT 제안 | 판정 |
|---|----------|------|
| 1 | Global Reset = "운에 기대는 방식". 제거하거나 횟수 제한 + deterministic fallback 필요 | **반은 맞고 반은 틀림** |
| 2 | 현재 격자 탐색 = "브루트포스(무작위에 가까움)". scoring 기반 선택으로 전환 필요 | **방향은 맞지만 현재 상태를 오독** |

### GPT가 틀린 부분

**"운에 기대는 방식"은 과장:**

Global Reset은 Random Retry가 아님. Choke Point intersects가 원인을 수학적으로 특정해서 Agent 3에 넘기는 구조:

```
buffer(450) 팽창 → 맞닿은 지점 = Choke Point 추출
→ Choke Point.intersects(기물 bbox) → 진짜 범인 추출
→ f-string으로 Agent 3에 "shelf_3tier가 통로를 물리적으로 차단함" 전달
```

정보가 있는 상태에서 재기획하는 것이지, 운에 기대는 게 아님.

**"무작위에 가까움"도 오독:**

현재 설계에 이미 정렬 기준이 있음:
```
격자점 생성 → wall_linestring 기준 거리 오름차순 정렬 → 순서대로 시도
```
"처음 되는 아무 위치"가 아니라 벽에 가까운 것부터 시도.

### GPT가 맞은 부분 (핵심 1개)

> "Agent 3이 끝까지 실패할 때의 최종 fallback이 없다"

이건 실제로 현재 설계에 구멍이 맞았음. → **Issue 15로 추가됨.**

---

## 2. Issue 15 — Deterministic Fallback (핵심)

### 왜 이 문제가 반복 출현했는가

이 세션 이전에 이미 3번 다뤄진 문제:

```
Issue 3:  cascade failure → Global Reset 도입
          단서: "무한루프 가능성 미해결" 메모

Issue 7:  zone 소진 = 자연 종료
          → 케이스 C 해결

Issue 15: zone 미소진 + 반복 실패
          → 케이스 D 해결 ← 이번 세션
```

매번 "한 가지 실패 케이스"를 잡을 때마다 인접한 틈이 새로 드러남.

### 근본 원인

**Global Reset은 "LLM이 더 나은 판단을 해줄 것"이라는 비결정적 전제에 의존.**

비결정적 시스템은 종료 조건을 수학적으로 보장할 수 없음. 그래서 케이스를 하나 잡을 때마다 옆에서 새 케이스가 생김.

### 실제 케이스 분류

```
케이스 A: 단독 배치 실패        → Issue 5 (Graceful Degradation) ✅
케이스 B: cascade failure       → Issue 3 (Global Reset + 재호출) ✅
케이스 C: zone 전부 소진        → Issue 7 (자연 종료) ✅
케이스 D: zone은 남아있지만
          Agent 3이 계속 같은
          나쁜 zone만 고름      → Issue 15 (Deterministic Fallback) ✅
```

> **사용자 지적**: "이거 그냥 zone 소진 후 행동이 없었던 거 아니냐?"
> → 맞음. 실패 zone을 허용 목록에서 빼면 결국 zone 소진으로 수렴.
> 케이스 D는 케이스 C의 "그 이후"가 없었던 것과 같은 문제.

### 확정된 구조 — 3단계 Fallback 계층

```
1단계: 정상 흐름
  Agent 3 기획 → 코드 순회 → 배치 시도

2단계: Global Reset (최대 2회)
  cascade 감지 → Choke Point 피드백 → Agent 3 재호출
  Agent 3은 실패 맥락 + 남은 zone 정보를 받아 재기획

3단계: Deterministic Fallback (2회 소진 후)
  LLM 개입 중단. 코드가 강제 배치:
  ① priority 높은 오브젝트부터 순서대로
  ② zone 제약 무시 — 전체 floor polygon에서 탐색
  ③ entrance blocking 절대 금지
  ④ 배치 가능한 위치 중 벽 최인접 선택
  ⑤ 그래도 불가 → Graceful Degradation (드랍)
```

### 핵심 원칙

**"시스템이 반드시 결과물을 내는 것"이 "기획 의도에 맞는 배치를 찾는 것"보다 우선.**

- "기획 의도에 맞는 배치" = Agent 3이 zone_label + direction을 기획 의도에 맞게 결정한 배치 (브랜드 규정 반영, 동선 고려, placed_because가 의미 있는 결과)
- Deterministic fallback = zone 무시하고 물리적으로 들어가는 곳에 넣는 것 (기획 의도 없음, 품질 낮음)
- fallback 배치 오브젝트는 `source: "fallback"` 표기

### 반영 위치

- [architecture_decisions.md](file:///c:/simhwa/rendy/architecture_decisions.md) — Issue 15
- [placement_planning.md](file:///c:/simhwa/rendy/.claude/skills/placement_planning.md) — "deterministic fallback — 최종 안전장치" 섹션

---

## 3. Issue 16 — 비정형 공간(ㄱ/ㄷ) Zone 분할

### 발견 경위

zone 판단이 어떻게 이루어지는지 질문 → "코드가 벽/Dead Zone으로 정적 분할" → "ㄱ자 공간이면 되냐?" → **안 됨**.

### 문제

Issue 10에서 "벽/Dead Zone으로 자연 구획되므로 정적 분할로 충분"이라고 했지만, **이건 직사각형 전제**. 비정형(오목형) 공간의 분할 규칙이 없음.

### 해결 방향 — Convex Decomposition

오목형(concave) polygon → 볼록형(convex) 하위 영역으로 분할하는 computational geometry 정립 알고리즘.

```
ㄱ (L-shape): 오목 꼭짓점 1개 → 2개 볼록 영역
ㄷ (U-shape): 오목 꼭짓점 2개 → 3개 볼록 영역
임의 형태:    오목 꼭짓점 N개 → N+1개 볼록 영역
```

ㄱ자를 풀면 ㄷ자, T자, 어떤 형태든 자동으로 풀림. 형태와 무관한 일반 해법.

### 미결

- 분할 알고리즘 선택 (Hertel-Mehlhorn 등)
- 분할된 zone에 zone_label 자동 부여 규칙 (벽면 방향? 입구 거리?)
- Shapely 내장 vs 외부 라이브러리

### 반영 위치

- [architecture_decisions.md](file:///c:/simhwa/rendy/architecture_decisions.md) — Issue 16

---

## 4. Issue 17 — 내부 벽/방 구분 + 복수 입구

### 발견 경위

실제 건축 도면(은행 평면도) 이미지 제시 → 현재 설계가 "오픈 플로어 하나"만 다루고 있다는 사실이 드러남.

### 문제

| 부재 항목 | 내용 |
|-----------|------|
| 배치 가능 영역 분류 | 전체 polygon에서 폐쇄된 방을 제외한 영역 추출 규칙 없음 |
| 내부 벽 처리 | Dead Zone인지, zone 경계인지, 무시 대상인지 정의 없음 |
| 복수 입구 | 소방 검증 시 경로 계산 달라짐. 가상 입구 선분도 복수 필요 |
| 좁은 복도 | 격자점 미생성 케이스. zone 분할 + 격자 순회에서 누락 가능 |

### 영향 범위

단순 미결이 아니라 **Agent 2 전반부(감지) + 후반부(계산) + 검증 모듈 전부**에 영향하는 아키텍처 수준 결정 필요.

### 반영 위치

- [architecture_decisions.md](file:///c:/simhwa/rendy/architecture_decisions.md) — Issue 17

---

## 5. Issue 18 — 곡선 벽 Polyline 근사 오차

### 발견 경위

곡선 벽을 polyline으로 근사하면 "충분하다"고 판단한 부분에 대해 → "건축 계열은 오차를 얼마나 허용하는데?" → **오차 수치를 정의하지 않았음.**

### 핵심 수치

| 세그먼트 수 (반지름 3000mm) | 최대 오차 | 소방 통로 위험 |
|---|---|---|
| 50개 | ~6mm | 통과/차단 판정 뒤집힐 수 있음 |
| 100개 | ~1.5mm | 시공 오차(±3~10mm) 이내 |
| 200개 | ~0.4mm | 무시 가능 |

### 문제의 본질

소방 통로 최소 폭(900mm)은 법적 기준 → 오차 허용 사실상 없음. polyline 근사 오차가 buffer(450) 판정을 뒤집으면 false negative(실제로는 막힌 통로를 통과로 판정) 발생.

### 반영 위치

- [architecture_decisions.md](file:///c:/simhwa/rendy/architecture_decisions.md) — Issue 18

---

## 6. 현재 미결 사항 전체 (총 7건)

| # | 항목 | 성격 |
|---|------|------|
| 1 | step_mm ratio | 수치 튜닝 |
| 2 | 소형/대형 공간 기준선 | 수치 튜닝 |
| 3 | inward 오프셋 규칙 | 규칙 정의 |
| 4 | center 오프셋 규칙 | 규칙 정의 |
| 5 | 비정형 공간 zone 분할 | 알고리즘 선택 |
| 6 | 내부 벽/방 구분 + 복수 입구 | **아키텍처 수준** |
| 7 | 곡선 벽 근사 오차 | 법적 기준 연동 |

> 1~4는 도면 테스트 후 결정 가능한 수치/규칙.
> 5~7은 아키텍처 구조에 영향을 주는 설계 결정.

---

## 7. 이 세션에서 수정된 파일

| 파일 | 변경 내용 |
|------|-----------|
| [architecture_decisions.md](file:///c:/simhwa/rendy/architecture_decisions.md) | Issue 15, 16, 17, 18 추가. "최적 해" 문구 수정. 미결 사항 7건으로 확장 |
| [placement_planning.md](file:///c:/simhwa/rendy/.claude/skills/placement_planning.md) | deterministic fallback 섹션 추가 |
