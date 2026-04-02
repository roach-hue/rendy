# Task Plan — 현재 상태

> 세션 시작 시 "지금 어디까지 왔나" 확인용. 상세 설계 결정 → `architecture_decisions.md`

---

## 현재 Phase: 아키텍처 설계 완료 → 구현 미시작

---

## 완료 (설계/기획)

- [x] Agent I/O 흐름 구조 va (`old/_Agent_IO_._va.md`)
- [x] 전체 개발 로드맵 va (`old/_._va (1).md`)
- [x] architecture_decisions.md (Issue 1~14 + 미결 사항)
- [x] for_gemini.md (변경 요약 + 기각 목록)
- [x] 주요 설계 결정 확정:
  - Agent 1: Regex 전처리 hybrid (텍스트 PDF)
  - Agent 3 output: zone_label 통일 (placement_slot 출력 금지)
  - cascade failure: Global Reset + Choke Point intersects 원인 추출
  - 물리적 한계: Graceful Degradation (단독 배치 테스트 분기)
  - NetworkX: 미세 조정 루프 제외, 확정 시 1회만
  - buffer(450) 근사 검증 + 가상 입구 선분 offset
  - step_mm: sqrt(w²+d²) × ratio 동적 계산
  - zone: Shapely Polygon 경계 + contains() 선행 체크
  - zone 순회: bounding box 격자점 → contains 필터 → 벽 거리 오름차순
  - 격자점 0개 fallback: 중앙 + 양 끝 3개
  - 관계 제약 검증: zone_label 비교 (C방식) → 실패 시 A→B
  - calculate_position: LineString + 수선의 발 (Issue 8)
  - outward: 더미 처리

---

## 테스트 후 조정 (구현 중 실측값으로 확정)

- [ ] step_mm ratio 수치 — 실제 도면 테스트 후 조정
- [ ] 소형/대형 공간 기준선 (usable_area_sqm) — 실제 도면 테스트 후 조정
- [ ] inward 오프셋 규칙 — 실제 오브젝트 크기 확인 후 조정
- [ ] center 오프셋 규칙 — 실제 오브젝트 크기 확인 후 조정

---

## 다음 작업

- [ ] **P0** 구현 시작 (명시적 지시 후 진행)
  - .claude/skills/ Agent별 상세 프롬프트 스펙
  - .claude/agents/ Agent 정의 파일
  - P0-1: dict 모듈 + space_data 스키마
  - P0-2: Agent 2 전반부 (OpenCV + Vision)
  - P0-3: Agent 2 후반부 (Dead Zone + NetworkX + LineString)
  - P0-4: Agent 1 (Regex + LLM 라벨링)
  - P0-5: Agent 3 + calculate_position + 코드 순회
  - P0-6: 검증 모듈 + Graceful Degradation
  - P0-7: .glb 생성 + Agent 5 리포트
