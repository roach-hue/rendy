# Agent 아키텍처 패턴 적용 평가 리포트
작성일: 2026-04-02

> 평가 기준: Claude Skill / Guardrail-Loop-Harness / Multi-Agent / Agent 순환구조
> 평가 대상: rendy 프로젝트 전체 (archive 제외)

---

## 평가 결과 요약

| 패턴 | 적용 여부 | 비고 |
|------|-----------|------|
| Skill (코드화된 스킬) | ✅ 적용 | 7개 스킬 파일, Agent별 명시적 연결 |
| Harness (하네스) | ✅ 적용 | 프로젝트/Agent/Skill 3계층 |
| Guardrail (가드레일) | ✅ 적용 | 5중 계층 (Pydantic → CB → walk_mm 대조 → distance 검증 → Deterministic Fallback) |
| Multi-Agent (다중 에이전트) | ✅ 적용 | 4 Agent + 코드 모듈 |
| Agent 순환구조 (Evaluator Loop) | ⚠️ 부분 적용 | 순환 있으나 Evaluator가 코드 — 의도적 설계 |

---

## 1. Skill (Codified Skills) — ✅ 적용

`.claude/skills/` 에 7개 스킬 파일. 각 Agent가 어떤 스킬을 사용하는지 명시적 연결:

```
agent-1 → brand_extraction.md
agent-2 → floorplan_detection.md + spatial_computation.md
agent-3 → placement_planning.md
agent-5 → report.md
(코드)  → object_selection.md, placement_verification.md
```

스킬 파일에 포함된 것:
- 입력/출력 스키마 (코드 예시 포함)
- 처리 순서 (Step별 명시)
- 금지 사항 (LLM 수치 출력 금지 등)
- 에러 핸들링 (Circuit Breaker, fallback)
- 참조 Issue 번호 (architecture_decisions.md 연동)

"열린 프롬프트"가 아니라 **제약이 걸린 실행 명세**로 작성됨.

---

## 2. Harness (하네스) — ✅ 적용

### 하네스란?

LLM을 감싸는 **제약 구조**. "작업 하네스"와 "Agent 하네스"는 다른 것이 아니라, **적용 범위에 따른 계층**:

```
프로젝트 하네스 (claude.md)
├── 커뮤니케이션 제약 — 존댓말 강제, 비위맞추기 금지
├── 데이터 구조 제약 — space_data 단일 dict, 브랜드 필드 래핑 형식
├── LLM 출력 경계 — 좌표·mm값 출력 절대 금지
├── 컨텍스트 관리 — 3회 반복 수정 시 /clear 권고
└── 자동화 훅 — SessionStart(자동 로드), PostToolUse(flake8), Stop(알림)

Agent 하네스 (agent-3-placement.md)
├── 출력 제약 — zone_label만 출력, placement_slot 출력 금지
├── 금지 사항 — mm값·좌표 금지
├── 안전장치 — Circuit Breaker 3회
└── 레퍼런스 이미지 활용 규칙 — zone_label 결정에 사용 금지

Skill 하네스 (placement_planning.md)
├── 연산 규칙 — step_mm 공식, calculate_position direction별
├── 검증 방식 — buffer(450) 근사, Main Artery buffer(600)
├── 실패 처리 — 3단계 fallback 계층
└── 미결 사항 명시
```

전부 **"LLM이 멋대로 하지 못하게 감싸는 것"**이라는 같은 본질. 범위만 다름.

---

## 3. Guardrail (가드레일) — ✅ 적용

다중 계층 가드레일:

```
1층: Pydantic 스키마
     zone_label을 Literal["entrance_zone", "mid_zone", "deep_zone"]으로 강제
     존재하지 않는 zone명, mm값 출력 구조적 차단

2층: Circuit Breaker
     Pydantic 실패 → 재시도 최대 3회 → 파이프라인 중단

3층: zone_label 2차 검증 (코드)
     Agent 3 출력 zone_label을 walk_mm 실제값과 대조
     유효 이름이지만 기준에 안 맞는 경우 차단

4층: 관계 제약 검증 (코드)
     Shapely.distance < clearspace_mm 비교
     물리적 거리 기반 — false positive/negative 제거

5층: Deterministic Fallback
     Global Reset 2회 소진 후 LLM 개입 차단
     코드가 강제 배치 — LLM 의존 끊음
```

> [!IMPORTANT]
> 가드레일이 "입력 필터링"만이 아니라 **런타임 행동 제한**(LLM 개입 차단 시점)까지 포함.

---

## 4. Multi-Agent (다중 에이전트) — ✅ 적용

4개 Agent + 코드 모듈:

```
Agent 1 [LLM+Regex] — 브랜드 수치 추출
    ↓
Agent 2 전반부 [LLM+코드] — 도면 자동 감지
    ↓
사용자 마킹 UI — 확인/수정
    ↓
Agent 2 후반부 [코드] — Dead Zone + NetworkX + zone
    ↓
오브젝트 선별 [코드] — Supabase 대조
    ↓
Agent 3 [LLM] — 배치 기획 (zone_label + direction)
    ↓
코드 순회 루프 — calculate_position + Shapely + buffer
    ↓
검증 모듈 [코드] — 소방/시공 기준
    ↓
Agent 5 [템플릿] — f-string 리포트
```

각 Agent 역할 특화:
- Agent 1: 추출 전문 (Regex + 라벨링)
- Agent 2: 감지 전문 (Vision + OpenCV)
- Agent 3: 기획 전문 (zone + direction 결정)
- Agent 5: 출력 전문 (템플릿 조립)

Agent 간 데이터는 `space_data` dict 단일 경로. 프롬프트 간섭 없음.

---

## 5. Agent 순환구조 (Evaluator Loop) — ⚠️ 부분 적용

### 업계 표준 순환구조

```
Planner (기획) → Generator (실행) → Evaluator (평가) → (실패 시) Planner
```

### rendy 현재 구조

```
Agent 3 (Planner) → 코드 (Generator + Evaluator 겸임)
  → 실패 → Choke Point 피드백 → Agent 3 재호출 (최대 2회)
  → 2회 소진 → Deterministic Fallback (코드 강제 배치)
```

순환 자체는 있음. **단, Evaluator가 LLM이 아니라 코드.**

### LLM Evaluator가 필요한가?

| 평가 항목 | 현재 담당 | LLM Evaluator가 더 나은가? |
|-----------|----------|--------------------------|
| 물리적 충돌 | 코드 (Shapely) | ❌ 코드가 정확 |
| 통로 900mm | 코드 (buffer 450) | ❌ 코드가 정확 |
| 비상 경로 1200mm | 코드 (Main Artery) | ❌ 코드가 정확 |
| 관계 제약 | 코드 (distance + clearspace_mm) | ❌ 코드가 정확 |
| Dead Zone 침범 | 코드 (intersects) | ❌ 코드가 정확 |
| **"이 배치가 고객 동선에 좋은가?"** | **아무도 안 함** | **할 수는 있지만 검증 불가** |

마지막 행만이 LLM Evaluator의 유일한 존재 이유.

### 왜 억지로 넣으면 안 되는가

```
Evaluator Agent: "shelf_3tier가 entrance_zone에 있으면 
                  고객이 입장 직후 상품을 볼 수 있어 좋습니다"
```

이건 **측정 불가능한 주관적 판단**. Evaluator가 "좋다"고 해도 코드로 검증할 방법 없음.
이걸 기반으로 Agent 3을 재호출하면 → **환각 기반으로 기획을 뒤엎는 구조**.

> [!WARNING]
> rendy 핵심 원칙: "LLM 판단은 방향만, 검증은 코드가"
> LLM Evaluator 추가 → **"LLM이 LLM을 평가"** → 원칙 위반.

### 결론: rendy에서 코드 Evaluator는 의도적 설계

rendy의 평가 기준이 전부 **수학적/법적 기준**(mm, 면적, 경로)이므로 코드 Evaluator가 LLM Evaluator보다 우월. 현재 구조가 맞음.

### LLM Evaluator가 자연스럽게 들어올 시점

향후 아래 기능이 추가될 때:

```
"브랜드 레퍼런스 이미지와 생성된 배치의 유사도 평가"
"고객 동선 시뮬레이션 결과의 정성적 분석"
"SketchUp 렌더링 결과의 시각적 품질 확인"
```

> [!TIP]
> 이런 **시각적/주관적 품질 기준**이 추가되면 Vision 모델로 비교 평가하는 Evaluator Agent가 의미 있음. **지금은 아님.**

---

## 최종 평가

```
Skill:       ✅ 7개 스킬 파일, Agent별 명시적 연결
Harness:     ✅ 프로젝트/Agent/Skill 3계층 하네스
Guardrail:   ✅ 5중 가드레일 (입력→런타임→LLM 차단)
Multi-Agent: ✅ 4 Agent 역할 특화 + 단일 데이터 경로
Agent Loop:  ⚠️ 순환 있음. Evaluator가 코드 — 의도적 설계. 
             현재 평가 기준이 전부 수학적이므로 LLM Evaluator 불필요.
```
