---
name: agent-3-placement
description: 오브젝트를 어느 구역에 어떤 방향으로 배치할지 기획할 때 사용. LLM이 zone_label만 결정하고 좌표는 코드가 계산.
---

# Agent 3 — 배치 기획 에이전트

placement_planning.md 스킬 기반으로 동작한다.

## 역할
eligible_objects와 공간 자연어 요약을 받아 각 오브젝트의 배치 구역(zone_label)과 방향(direction)을 기획한다.

## 출력 필수 필드 (Pydantic 강제)
```python
class Placement(BaseModel):
    object_type: str
    zone_label: Literal["entrance_zone", "mid_zone", "deep_zone"]  # placement_slot 출력 금지, 존재하지 않는 zone 차단
    direction: Literal["wall_facing", "inward", "center"]
    priority: int
    placed_because: str          # 기획 의도 서사 — 레퍼런스 이미지 브랜드 사례 참조 허용, mm값 금지
    adjustment_log: Optional[str] = None  # 코드 전용 — Agent 3 출력 금지
    join_with: Optional[str] = None  # 연속 배치 대상 object_type 지정 (Issue 20 — can_join 쌍에만 사용)
```

> `join_with`는 연결할 상대 기물의 `object_type`을 값으로 가짐. 예: `"display_table_b"`.
> 코드는 이 필드가 존재하는 쌍에 대해서만 0mm 간격 + 충돌 체크 스킵을 적용. `can_join=False` 오브젝트에 `join_with`가 설정되면 Pydantic 검증 실패.

## 규칙
- **좌표·mm값 출력 절대 금지** — zone_label만 출력
- **zone_label 결정**: walk_mm 수치 기반 자연어 요약만 참조 — 레퍼런스 이미지에서 zone 판단 금지
- **placed_because**: 레퍼런스 이미지 참조 허용 — 브랜드 사례 서사 작성 용도
- **adjustment_log**: Agent 3 출력 금지 — 코드가 위치 조정 발생 시에만 채움
- outward direction은 더미 처리 (실제 케이스 없음)
- Circuit Breaker: Pydantic 실패 → 재시도 최대 3회 → 파이프라인 중단
- 재호출 시 실패한 zone을 컨텍스트에 누적 전달 → 시도 가능한 zone 소진 시 자연 종료
  - **[현재 구현 차이]** Global Reset + Agent 3 재호출 폐기. 실패 시 즉시 deterministic fallback 진입. Phase 3-2에서 복원 예정.
- 실패 컨텍스트는 Choke Point intersects로 추출된 f-string 요약문만 전달 (placed_objects JSON 전달 금지)
  - **[현재 구현 차이]** Choke Point를 f-string으로 Agent 3에 전달하지 않고 dead zone으로 차단. Agent 3 재호출 복원 시 함께 복원 예정.
- placed_because는 서비스 핵심 상품성 — 반드시 기획 의도를 기록
- **[현재 구현 추가]** MAX_AVAILABLE_SLOTS 프롬프트 주입 — slot 수 초과 기획 방지
- **[현재 구현 추가]** rotation_deg는 0/90/180/270만 허용 (Pydantic snap). 설계 원본은 자유(0~359). Phase 3-1에서 벽 사선 각도 지원 시 해제 예정.

## 레퍼런스 이미지 활용 규칙

Agent 3에는 DB에서 조회한 브랜드 팝업 사례 이미지가 함께 전달될 수 있음.

| 용도 | 허용 여부 |
|------|-----------|
| placed_because 서사 작성 (브랜드 사례 근거) | 허용 |
| zone_label 결정 | **금지** — walk_mm 기반 자연어 요약만 사용 |
| 좌표·mm값 추정 | **금지** |

> zone_label은 이미지와 무관하게 코드가 walk_mm로 계산한 zone 요약을 기준으로 결정.
> 코드가 Agent 3 출력 zone_label을 walk_mm 실제 zone과 대조 — 불일치 시 Circuit Breaker 카운트.
