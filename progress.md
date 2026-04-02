# Progress Log

> 세션별 완료 내용, 에러, 다음 시작점 기록.

---

## 2026-04-01

### 완료 (설계/기획 세션)

- Agent I/O va 기반으로 아키텍처 전면 재설계
- architecture_decisions.md 생성 (Issue 1~14)
- Gemini와 설계 검토 — 주요 변경 반영
- for_gemini.md 생성 (변경 요약 전달용)
- architecture_review.md 기반 4개 오류 수정:
  - Issue 6/8 공존 → Issue 6 폐기 표시
  - inward/outward/center 중심점 오류 수정
  - 격자점 0개 fallback (중앙 + 양 끝 3개)
  - 관계 제약 검증 (Issue 14 — zone_label 비교 기각 → Shapely.distance + clearspace_mm 확정)
- outward direction 더미 처리
- task_plan.md + progress.md 생성

### 주요 결정 (오늘)

- Agent 3 output: zone_label 통일
- cascade failure: Global Reset + Choke Point intersects
- NetworkX: 확정 시 1회만 (미세 조정 루프 제외)
- buffer(450) 근사 + 가상 입구 선분 offset
- step_mm: sqrt(w²+d²) × ratio
- 관계 제약: Shapely.distance < clearspace_mm로 검증 (Issue 14 — zone_label 비교 기각)

### 에러/주의

- 없음

### 다음 세션 시작 지점

- 미결 4개 확인 후 P0 구현 시작 (명시적 지시 필요)
- .claude/skills/ + agents/ 는 구현 시작 시점에 생성

---

## 2026-04-02

### 완료 (하네스 동기화 세션)

- 클로드 코드: 전체 md 파일 하네스 엔지니어링 형태 동기화
  - archive/2026-04-02/ 백업 (architecture_decisions, architecture_spec, agents 4개, skills 7개)
  - brand_extraction.md Issue 14 기각 방식 수정
  - agent-2-floorplan.md Issue 16-22 반영
  - agent-5-report.md Issue 15 fallback source 반영
  - claude.md ParsedDrawings + zone_label 용어 수정
  - architecture_spec.md inward/center Issue 17/21 반영 (1/3 완료 후 세션 한도)
- Gemini(Antigravity): 클로드 코드 끊긴 작업 이어서 완료
  - architecture_spec.md ceiling_height_mm 추가 (Issue 22)
  - architecture_spec.md 테스트 후 조정 테이블 해소 항목 표기
  - progress.md Issue 14 기록 업데이트
  - claude.md Agent 3 재호출 피드백 규칙 업데이트 (Issue 12)

### 에러/주의

- 클로드 코드 세션 한도 (2pm KST 리셋)

### 다음 세션 시작 지점

- architecture_decisions_part1/2a/2b.md 정리 여부 결정 (마스터와 중복)
- P0 구현 시작 (명시적 지시 필요)
