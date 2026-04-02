# 랜딩업 아키텍처 문서 비교 평가
평가일: 2026-04-01

> **2026-04-02 현재 해소 상태**
> - ① relationships 제약 → Issue 14 (Shapely.distance)로 해소
> - ② Agent 3 재호출 상한 → Issue 15 Deterministic Fallback + Circuit Breaker로 해소
> - ③ blocking 기준 → placement_verification.md에 명시됨
> - ① Issue 3 무한루프 → Issue 15로 해소
> - ② Issue 6 중심점 오류 → Issue 17 Hybrid Sampling + Issue 21 Width Perpendicular로 해소
> - ③ Issue 6/8 공존 → Issue 6 SUPERSEDED 표시됨
> - ④ Issue 13 격자점 0개 → fallback 3개(중앙+양끝) 확정
> - ⑤ 미결 수치 → step_mm ratio, zone 임계값은 여전히 도면 테스트 후 결정

---

## 평가 대상

| 문서 | 역할 |
|------|------|
| `_Agent_IO___va.md` | 전체 파이프라인 I/O 흐름 구조 |
| `architecture_decisions.md` | 개별 이슈별 의사결정 기록 |

---

## `_Agent_IO___va.md` 평가

### 구조적 문제점

**① relationships 제약의 실행 경로가 끊겨 있습니다.**

"라이언과 춘식이를 떨어뜨릴 것"을 Agent 3 프롬프트에 자연어로 전달한다고 했는데, Agent 3 output 스키마에 이 제약이 실제로 반영됐는지 확인하는 메커니즘이 없습니다. Agent 3이 `placed_because`에 언급하는 것과 실제로 두 오브젝트를 다른 placement_slot에 배치하는 것은 다릅니다. Shapely는 수치 충돌만 잡고, 관계 제약 위반은 아무도 잡지 않습니다.

**② Agent 3 재호출 상한이 두 카운터로 분리돼 있어 총 상한이 불명확합니다.**

Shapely 실패 시 Agent 3 재호출 최대 2회, Pydantic 실패 시 Circuit Breaker 3회로 별도 카운터가 돌아갑니다. 두 실패가 섞이면 총 몇 회까지 재호출이 발생하는지 상한이 정의되지 않았습니다.

**③ 검증 모듈의 blocking 기준이 없습니다.**

"blocking이면 차단, 아니면 통과"라고만 돼 있는데 무엇이 blocking인지 정의가 없습니다. 소방 기준 미달인지, Dead Zone 침범인지, 통로 폭 미달인지 — 기준이 명시돼야 `.glb` 출력 차단 로직이 구현 가능합니다.

### 잘 된 부분

**LLM/코드 역할 분리가 명확합니다.** "Agent 3은 zone_label만 받고 좌표는 구조적으로 출력 불가"라는 설계는 환각 차단 방식 중 가장 확실한 방법입니다. Pydantic 스키마로 구조 강제한 것도 이 원칙을 코드 레벨에서 보강합니다.

**Agent 2 분리 이유가 실행 가능한 논리입니다.** "전부 모은 다음에 한 번에 계산"이 재계산 낭비를 막는 올바른 판단이며, 사용자 마킹 → 후반부 계산 순서가 데이터 흐름상 자연스럽습니다.

**실패 처리 4단계 분류가 구체적입니다.** 추출 실패 / 감지 실패 / 배치 실패 / 스키마 실패를 각각 다른 방식으로 처리하는 구조는 실제 구현 시 분기가 명확합니다.

---

## `architecture_decisions.md` 평가

### 구조적 문제점

**① Issue 3 — 무한루프 미해결이 문서 전체에서 해소되지 않습니다.**

"동일 reasoning 반복 → 무한루프 가능성 미해결"이라고 직접 인정했는데, Issue 7에서 재호출 최소화를 다루면서도 "같은 실패 패턴을 반복할 때 언제 포기하냐"는 종료 조건이 없습니다. Agent 3이 매번 동일한 배치를 결정하면 Global Reset이 무한 반복됩니다. 최대 재호출 횟수 하드캡이 없으면 이 설계는 최악의 경우 무한루프입니다.

**② Issue 6 — inward / outward / center의 중심점 계산이 동일합니다.**

세 direction 모두 `placement_slot.x, placement_slot.y`로 같은 좌표를 씁니다. 회전각만 다르면 오브젝트 중심점이 같은 위치에 생성되어 세 방향 오브젝트가 겹칩니다. 의도적인 설계인지 오류인지 문서에서 판단이 불가능합니다.

**③ Issue 8이 Issue 6을 사후에 덮어썼는데 Issue 6이 폐기 표시 없이 남아있습니다.**

Issue 6은 `wall_surface_y` 단일 좌표 기준으로 작성됐고, Issue 8에서 이를 LineString + 수선의 발 방식으로 교체했습니다. 두 스펙이 폐기 표시 없이 같은 문서에 공존합니다. 구현자가 어느 스펙을 따라야 하는지 알 수 없습니다.

**④ Issue 13 — step_mm이 zone 크기보다 크면 격자점이 0개입니다.**

zone polygon 안에 step_mm 격자점을 생성하는데, step_mm이 zone 크기보다 크면 격자점이 하나도 생성되지 않습니다. 이 케이스에서 attempt_placement가 어떻게 동작하는지 처리 로직이 없습니다.

**⑤ 미결 수치가 전체 분기 구조의 검증 블로커입니다.**

`step_mm ratio`와 `소형/대형 공간 기준선` 두 값을 "테스트 후 결정"이라고 명시했는데, 이 값이 결정되기 전까지는 Issue 7의 분기 로직 전체가 동작 검증 불가능합니다. 단순 수치 미결이 아니라 구조 검증 블로커임을 명시해야 합니다.

### 잘 된 부분

**Issue 12 — Choke Point intersects 방식이 가장 탄탄합니다.** 거리 기반을 완전히 폐기하고 교차 기반으로 전환해 도면 크기 무관하게 동작하며, LLM에 수치 환각 여지를 원천 차단합니다. f-string 기계 조립으로 LLM이 요약문을 생성하지 않고 읽기만 하는 구조도 올바릅니다.

**Issue 7 — cascade failure vs 물리적 한계 구분 로직이 실행 가능합니다.** 단독 배치 테스트로 원인을 수학적으로 분기하는 것이 명확하고, 두 케이스를 같은 실패로 묶지 않은 판단이 맞습니다.

**Issue 11 — buffer 근사 + NetworkX 최종 1회 구조가 합리적입니다.** false positive 감수 trade-off 판단이 명확하고, false negative보다 안전한 방향을 선택한 근거가 있습니다.

**Issue 4 기각 이유가 구체적입니다.** 사전 분석 레이어를 "가벼운 근사치는 거짓 정보 주입"이라는 이유로 기각한 판단은 LLM 환각 위험을 정확히 짚었습니다.

---

## 두 문서 간 충돌

| 항목 | `_Agent_IO___va.md` | `architecture_decisions.md` |
|------|--------------------|-----------------------------|
| Agent 3 재호출 상한 | Shapely 실패 시 최대 2회 명시 | 재호출 상한 미명시 |
| 무한루프 종료 조건 | Circuit Breaker 3회 (Pydantic 한정) | 미해결로 인정, 해결책 없음 |
| wall 계산 방식 | 명시 없음 | Issue 6 (단일 좌표)와 Issue 8 (LineString) 공존 |

두 문서가 같은 시스템을 설명하는데 Agent 3 재호출 상한이 다릅니다. 구현 시 어느 문서를 기준으로 잡을지 결정이 필요합니다.

---

## 요약

| 평가 항목 | `_Agent_IO___va.md` | `architecture_decisions.md` |
|----------|--------------------|-----------------------------|
| LLM/코드 역할 분리 | 명확 | 이슈별 명확하나 일부 공존 스펙 혼재 |
| 실패 시나리오 처리 | 4단계 분류 있음 | cascade/물리적 한계 구분 있으나 무한루프 미해결 |
| 토큰/비용 제어 | 재호출 상한 명시 | 상한 미명시 |
| 환각 통제 | 구조적 차단 (Pydantic) | Choke Point로 수치 환각 차단 |
| 구현 불가 구간 | 관계 제약 검증 없음 | Issue 6/8 스펙 충돌, 격자점 0개 케이스 |
