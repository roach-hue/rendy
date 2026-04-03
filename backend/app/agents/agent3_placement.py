"""
Agent 3 — 배치 기획 에이전트 (LLM)

eligible_objects + 공간 요약 + 브랜드 제약 → Placement 리스트 생성.
LLM은 zone_label + direction + priority만 결정. 좌표·mm값 출력 금지.

Circuit Breaker: Pydantic 검증 실패 시 최대 3회 재시도.
"""
import json
import re

import anthropic

from app.schemas.placement import Placement


def _get_client() -> anthropic.Anthropic:
    return anthropic.Anthropic()


_SYSTEM_PROMPT = """당신은 팝업 스토어 공간 기획 전문가입니다.
주어진 공간 정보와 오브젝트 목록을 보고, 각 오브젝트를 어느 zone에 어떤 방향으로 배치할지 기획하세요.

규칙:
- JSON 배열만 출력. 다른 텍스트 금지.
- 각 오브젝트에 대해: object_type, zone_label, direction, priority, placed_because를 결정.
- zone_label: "entrance_zone" | "mid_zone" | "deep_zone" 중 하나. 공간 요약의 walk_mm 기준으로 판단.
- direction: "wall_facing" | "inward" | "center" 중 하나.
  - wall_facing: 벽에 등 대고 정면이 내부를 향함 (선반, 진열대 등)
  - inward: 공간 내부에서 입구 방향을 바라봄 (캐릭터, 포토존 등)
  - center: 공간 중앙을 향함 (테이블, 디스플레이 등)
- priority: 1이 가장 높음 (먼저 배치). 메인 오브젝트를 높은 우선순위.
- placed_because: 기획 의도 서사. mm값 포함 금지. "입구에서 첫 시선이 닿는 위치" 같은 서사.
- rotation_deg: 반드시 0, 90, 180, 270 중에서만 선택하라. 임의의 각도(15, 33, 45 등)를 사용하지 마라. 불필요하면 생략.
- join_with: can_join=true인 오브젝트끼리 연속 배치 시 상대 object_type 지정.
- 좌표, mm 수치 출력 절대 금지.

배치 전략:
- entrance_zone: 방문객 첫 인상. 브랜드 시그니처 오브젝트, 환영 캐릭터.
- mid_zone: 메인 동선. 제품 진열, 체험 공간.
- deep_zone: 깊은 구역. 포토존, 메인 어트랙션 (체류 유도).
- 캐릭터는 inward (입구를 바라봄), 선반은 wall_facing, 테이블은 center.
- 브랜드 쌍 규정 반드시 준수 (분리/합체 규칙).
- MAX_AVAILABLE_SLOTS 개수를 초과하는 오브젝트를 기획하지 마라. 공간에 물리적으로 배치 가능한 슬롯 수가 제한되어 있다. 후보 중 우선순위가 높은 것을 선별하라.
"""


def plan_placement(
    eligible_objects: list[dict],
    space_data: dict,
    brand_data: dict,
) -> list[Placement]:
    """
    Agent 3 메인 함수.
    eligible_objects + 공간 요약 → Placement 리스트.
    Circuit Breaker: 최대 3회 재시도.
    """
    agent3_summary = space_data.get("_agent3_summary", "공간 요약 없음")

    # MAX_AVAILABLE_SLOTS: 공간의 물리적 배치 가능 수
    max_slots = sum(
        1 for k, v in space_data.items()
        if isinstance(v, dict) and "zone_label" in v and k != "floor"
    )

    # Agent 3에는 object_type + category만 전달 (수치 금지)
    obj_list = [
        {"object_type": o["object_type"], "category": o["category"],
         "can_join": o.get("can_join", False)}
        for o in eligible_objects
    ]

    # 브랜드 제약 텍스트 구성
    brand_text = _format_brand_constraints(brand_data)

    user_prompt = f"""## 공간 정보
{agent3_summary}

## 물리적 제약
MAX_AVAILABLE_SLOTS = {max_slots}
반드시 {max_slots}개 이하로 오브젝트를 기획하라. 공간의 물리적 한계를 초과하면 안 된다.
오브젝트 목록에서 우선순위가 높은 것을 선별하여 {max_slots}개 이내로 배치 기획을 작성하라.

## 배치 가능 오브젝트 (후보)
{json.dumps(obj_list, ensure_ascii=False, indent=2)}

## 브랜드 제약
{brand_text}

위 정보를 바탕으로 각 오브젝트의 배치 기획을 JSON 배열로 출력하세요.
{max_slots}개를 초과하지 마세요.
"""

    last_error = None
    for attempt in range(3):
        try:
            raw = _call_llm(user_prompt)
            placements = _parse_and_validate(raw, eligible_objects)
            print(f"[Agent3] success on attempt {attempt + 1}: {len(placements)} placements")
            return placements
        except Exception as e:
            last_error = e
            print(f"[Agent3] attempt {attempt + 1} failed: {e}")
            continue

    from app.core.exceptions import CircuitBreakerTrippedError
    raise CircuitBreakerTrippedError(
        f"Agent 3 배치 기획 3회 실패: {last_error}",
        context={"attempts": 3, "last_error": str(last_error)},
    )


def _call_llm(user_prompt: str) -> str:
    """Claude API 호출."""
    response = _get_client().messages.create(
        model="claude-sonnet-4-5",
        max_tokens=4096,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )
    raw = response.content[0].text.strip()
    print(f"[Agent3] LLM response: {len(raw)} chars")
    return raw


def _parse_and_validate(raw: str, eligible_objects: list[dict]) -> list[Placement]:
    """LLM 응답 파싱 + Pydantic 검증."""
    # JSON 배열 추출
    match = re.search(r"\[.*\]", raw, re.DOTALL)
    if not match:
        raise ValueError(f"JSON 배열 파싱 실패: {raw[:200]}")

    items = json.loads(match.group())

    eligible_types = {o["object_type"] for o in eligible_objects}
    placements = []

    for item in items:
        obj_type = item.get("object_type", "")
        if obj_type not in eligible_types:
            print(f"[Agent3] skip unknown object_type: {obj_type}")
            continue

        placement = Placement(
            object_type=obj_type,
            zone_label=item["zone_label"],
            direction=item["direction"],
            priority=item.get("priority", len(placements) + 1),
            rotation_deg=item.get("rotation_deg"),
            placed_because=item["placed_because"],
            join_with=item.get("join_with"),
        )
        placements.append(placement)

    if not placements:
        raise ValueError("유효한 Placement 0개")

    return placements


def _format_brand_constraints(brand_data: dict) -> str:
    """브랜드 제약을 텍스트로 포맷."""
    lines = []
    for key in ["clearspace_mm", "logo_clearspace_mm", "character_orientation", "prohibited_material"]:
        field = brand_data.get(key, {})
        if isinstance(field, dict) and field.get("value") is not None:
            lines.append(f"- {key}: {field['value']}")

    pair_rules = brand_data.get("object_pair_rules", [])
    for r in pair_rules:
        rule_text = r.get("rule", r) if isinstance(r, dict) else str(r)
        lines.append(f"- 쌍 규정: {rule_text}")

    return "\n".join(lines) if lines else "없음"
