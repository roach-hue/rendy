---
name: agent-5-report
description: 배치 완료 후 최종 리포트를 생성할 때 사용. f-string 템플릿으로 기계 조립 (LLM 아님).
---

# Agent 5 — 리포트 생성 에이전트

report.md 스킬 기반으로 동작한다.

## 역할
배치 결과(dict + placements + 검증 결과)를 받아 f-string 템플릿으로 최종 리포트를 기계 조립한다.

## 출력 포함 내용
- source별 수치 표기 (브랜드 메뉴얼 추출 / 기본값 / 사용자 입력)
- placed_because (Agent 3 기획 의도 서사)
- adjustment_log (코드 위치 조정 발생 시 — "1차 지정 위치 X → Y 자동 조정 (거리: Nmm)")
- source: "fallback" 오브젝트 목록 (Deterministic Fallback 배치 — Agent 3 기획 아님 명시)
- 배치 불가 오브젝트 목록 + 사유
- 면책 조항 (disclaimer)

## 규칙
- LLM이 요약문을 생성하는 게 아니라 f-string 템플릿으로 기계 조립
- 수치 환각 원천 차단 — 모든 수치는 space_data에서 직접 참조
- disclaimer 항목이 있으면 반드시 포함
- 배치 불가 오브젝트가 있으면 사유와 함께 반드시 명시
