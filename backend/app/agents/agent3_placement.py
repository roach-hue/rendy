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

최우선 원칙 — 사용자 의도 우선(User Intent Override):
- 사용자가 직접 입력한 기획 지시(user_instruction)가 있으면, 아래의 모든 표준 규칙과 상업 원칙보다 우선한다.
- 사용자 명령이 표준 규칙과 충돌하면(예: "입구 옆에 카운터를 놓아라"), 표준 규칙을 즉시 무시하고 사용자 의도를 1순위로 실행하라.
- 사용자의 의도는 '특별한 기획적 예외'로 간주. 벽 관통이나 기물 겹침 같은 물리적 오류만 거부하라.
- user_instruction이 없으면 아래 표준 규칙을 그대로 따른다.

규칙:
- JSON 배열만 출력. 다른 텍스트 금지.
- 각 오브젝트에 대해: object_type, zone_label, direction, priority, alignment, placed_because를 결정.
- zone_label: "entrance_zone" | "mid_zone" | "deep_zone" 중 하나. 공간 요약의 walk_mm 기준으로 판단.
- direction: "wall_facing" | "inward" | "center" 중 하나.
  - wall_facing: 벽에 등 대고 정면이 내부를 향함 (선반, 진열대 등)
  - inward: 공간 내부에서 입구 방향을 바라봄 (캐릭터, 포토존 등)
  - center: 공간 중앙을 향함 (테이블, 디스플레이 등)
- priority: 1이 가장 높음 (먼저 배치). 메인 오브젝트를 높은 우선순위.
- alignment: 벽면 대비 기물 정렬 방식. 숫자 각도 금지 — 의도만 선택하라.
  - "parallel": 벽면과 나란히 배치 (기본값, 선반/진열대 등)
  - "perpendicular": 벽면에서 수직으로 튀어나오게 배치 (파티션, 칸막이 등)
  - "opposite": 벽면을 등지고 반대로 배치 (캐릭터가 입구를 향할 때)
  - "none": 벽면 각도 무시 (중앙 자유 배치)
- placed_because: 기획 의도 서사. mm값·숫자+mm 절대 금지. "1200mm" "900mm" "2000mm" 같은 표현 금지. "입구에서 첫 시선이 닿는 위치" "우측 벽면 히어로 배치" 같은 순수 서사만.
- join_with: can_join=true인 오브젝트끼리 연속 배치 시 상대 object_type 지정.
- 좌표, mm 수치, rotation 숫자 출력 절대 금지. 회전은 alignment로만 표현.

배치 전략:
- entrance_zone: 방문객 첫 인상. 브랜드 시그니처 오브젝트, 환영 캐릭터.
- mid_zone: 메인 동선. 제품 진열, 체험 공간.
- deep_zone: 깊은 구역. 포토존, 메인 어트랙션 (체류 유도).
- 캐릭터는 inward (입구를 바라봄), 선반은 wall_facing, 테이블은 center.
- 브랜드 쌍 규정 반드시 준수 (분리/합체 규칙).
- MAX_AVAILABLE_SLOTS 개수를 초과하는 오브젝트를 기획하지 마라. 후보 중 우선순위가 높은 것을 선별.

Rendy 배치 표준 5규칙 (최우선 준수 — 위반 시 배치 무효):

[R1. 전이 지대] 입구 반경 1.5m~2m는 무조건 비워라. 이 영역에 기물을 배치하지 마라. (물리 엔진이 이미 슬롯을 파괴했으므로, entrance_zone 중에서도 walk_mm이 가장 낮은 슬롯은 피하라.)

[R2. 자석 효과] POS_COUNTER(계산대)는 반드시 walk_mm이 가장 높은 최후방 코너(deep_zone)에 배치하라. 고객이 매장 끝까지 이동하게 유도.

[R3. 히어로 존] 입구 직후 전면 1/3 지점(entrance_zone과 mid_zone 경계)에 메인 매대(display_table 등)를 배치하라. 진입 직후 시선을 사로잡는 역할.

[R4. 시야각 제약 — 절대 규칙]
  - 중앙 슬롯(tags에 "center_area" 포함): height_mm 1200 이하 오브젝트만 배치. 시야 차단 방지.
  - 벽면 슬롯(tags에 "wall_adjacent" 포함): height_mm 1500 이상 오브젝트 우선. 벽면 높이 활용.
  - entrance_zone: height_mm 1200 초과 배치 절대 금지!!! 캐릭터 패널(2000mm), 배너(2000mm), 포토존(2400mm)은 entrance_zone에 놓으면 안 된다. 반드시 mid_zone 또는 deep_zone에 배치. entrance_zone에는 display_table(800mm), shelf_3tier(1200mm) 같은 낮은 기물만 허용.

[R5. 동선 폭] 기물 간 간격 최소 900mm~1200mm 유지. 물리 엔진이 충돌/통로 검증을 하지만, 기획 단계에서도 같은 슬롯에 2개 이상 몰아넣지 마라. 인접 슬롯보다 분산 배치 우선.

상업 3대 원칙 (Core Logic — 전문가 수준 배치):

[P1. 오른쪽 우선의 법칙 — Power Wall]
입구 진입 기준 우측 벽면은 브랜드 인상의 70%를 결정하는 가장 중요한 벽이다.
슬롯 목록에서 wall_normal이 입구 진입 방향 기준 우측에 해당하는 벽면 슬롯을 식별하라.
obj_list 중 가장 화려하거나 핵심적인 기물(Hero Object — 캐릭터 패널, 포토존, 메인 진열대)을 이 우측 벽면에 최우선 배치하라.
우측 벽면에 Hero가 없으면 배치 실패로 간주.

[P2. 카테고리 인접성 — Logical Clustering]
동일 category의 기물은 파편화하지 말고 인접한 슬롯에 군집(Cluster)으로 배치하라.
예: shelf_wall 2개가 있으면 같은 벽면의 인접 슬롯에 나란히 배치. character 3개가 있으면 같은 zone 내 연속 슬롯에 배치.
서로 다른 카테고리는 zone이나 벽면으로 분리하여 시각적 구획을 만들어라.
placed_because에 "같은 카테고리 군집" 또는 "브랜드 월(Brand Wall)" 등 군집 의도를 명시.

[P3. 시선 고정 지점 — Focal Point]
입구 정면 시야의 끝(deep_zone, walk_mm 최대 구역)에 고객의 심부 진입을 유도하는 대형 오브젝트를 강제 배치하라.
photo_zone_structure, 대형 캐릭터 패널, 미디어 기물 등 height_mm가 가장 크고 시각적으로 압도적인 기물이 Focal Point 후보.
Focal Point가 없으면 고객이 입구에서 돌아서므로, deep_zone에 반드시 1개 이상 대형 기물을 배치.

[P4. 주동선 종속 배치 — Spine-First Placement]
공간에는 입구에서 가장 깊은 벽면 중앙까지 관통하는 직각 주동선(Main Spine)이 미리 깔려 있다.
각 슬롯에는 주동선과의 논리적 거리를 나타내는 spine 메타데이터가 부여되어 있다:
  - spine=adjacent: 주동선에서 2m 이내. 고객이 반드시 지나가는 핵심 구역.
  - spine=nearby: 주동선에서 2~5m. 동선에서 한 눈에 보이는 준핵심 구역.
  - spine=far: 주동선에서 5m 이상. 동선에서 벗어난 보조 구역.
배치 원칙:
  - Hero Object(캐릭터, 메인 매대, 포토존): 반드시 spine=adjacent 슬롯에만 배치.
  - 진열 선반, 체험 테이블: spine=adjacent 또는 spine=nearby 슬롯에 배치.
  - 배너, 보조 선반: spine=far 슬롯에 배치 가능. 핵심 기물은 절대 far에 놓지 마라.
기물의 정면(direction)은 주동선을 향해야 한다:
  - 주동선 양측 벽면의 기물 → direction="inward" (동선 쪽을 바라봄)
  - 주동선 끝(Focal Point) → direction="inward" (걸어오는 고객을 맞이함)
placed_because에 "주동선 인접(adjacent) 배치" 또는 "동선 끝 Focal Point" 등 동선 종속 의도를 명시.
"""


def plan_placement(
    eligible_objects: list[dict],
    space_data: dict,
    brand_data: dict,
    feedback: str = "",
    user_instruction: str = "",
) -> list[Placement]:
    """
    Agent 3 메인 함수.
    eligible_objects + 공간 요약 → Placement 리스트.
    feedback: 이전 배치 실패 피드백 (재호출 시 전달).
    user_instruction: 사용자 직접 기획 지시 (표준 규칙 Override).
    Circuit Breaker: 최대 3회 재시도.
    """
    agent3_summary = space_data.get("_agent3_summary", "공간 요약 없음")

    # MAX_AVAILABLE_SLOTS: 공간의 물리적 배치 가능 수
    max_slots = sum(
        1 for k, v in space_data.items()
        if isinstance(v, dict) and "zone_label" in v and k != "floor"
    )

    # Main Spine 경유점 추출 (Agent 3에 동선 구조 전달)
    spine_text = _format_spine_info(space_data)

    # Agent 3에는 object_type + category + height_mm 전달 (좌표 금지, 규격은 허용)
    obj_list = [
        {"object_type": o["object_type"], "category": o["category"],
         "height_mm": o.get("height_mm", 0), "can_join": o.get("can_join", False)}
        for o in eligible_objects
    ]

    # 브랜드 제약 텍스트 구성
    brand_text = _format_brand_constraints(brand_data)

    # IQI: 면적 기반 적정 수량 계산
    usable_area_sqm = space_data.get("floor", {}).get("usable_area_sqm", 100)
    usable_area_mm2 = usable_area_sqm * 1_000_000
    avg_footprint = sum(o["width_mm"] * o["depth_mm"] for o in eligible_objects) / max(len(eligible_objects), 1)
    iqi_max_count = int((usable_area_mm2 * 0.25) / avg_footprint) if avg_footprint > 0 else max_slots
    recommended_count = min(iqi_max_count, max_slots)

    user_prompt = f"""## 공간 정보
{agent3_summary}

## 물리적 제약
MAX_AVAILABLE_SLOTS = {max_slots}
IQI_RECOMMENDED_COUNT = {recommended_count}
유효 면적 = {usable_area_sqm}m², 기물 점유 상한 = 면적의 25%
기물 평균 면적 = {avg_footprint/1_000_000:.2f}m² → 적정 배치 수 = {recommended_count}개
{recommended_count}개를 목표로 기획하라. {max_slots}개를 절대 초과하지 마라.
슬롯을 다 채우지 말고, 동선 확보와 시각적 여유를 위해 적정 수량만 선별하라.

## 주동선(Main Spine) 구조
{spine_text}

## 배치 가능 오브젝트 (후보)
{json.dumps(obj_list, ensure_ascii=False, indent=2)}

## 브랜드 제약
{brand_text}

위 정보를 바탕으로 각 오브젝트의 배치 기획을 JSON 배열로 출력하세요.
{max_slots}개를 초과하지 마세요.
"""

    # 사용자 의도 Override 주입 (표준 규칙보다 우선)
    if user_instruction:
        user_prompt += f"""

## 사용자 기획 지시 (최우선 — 표준 규칙보다 우선)
{user_instruction}
위 지시가 표준 규칙과 충돌하면 사용자 지시를 따르세요. 물리적 오류(벽 관통, 겹침)만 거부.
"""

    # 재호출 피드백 주입
    if feedback:
        user_prompt += f"""

## 이전 배치 실패 피드백
아래 오브젝트가 이전 시도에서 배치 실패했습니다. 다른 zone이나 direction/alignment으로 재기획하세요.
{feedback}
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
            alignment=item.get("alignment", "parallel"),
            placed_because=item["placed_because"],
            join_with=item.get("join_with"),
        )
        placements.append(placement)

    if not placements:
        raise ValueError("유효한 Placement 0개")

    return placements


def _format_spine_info(space_data: dict) -> str:
    """
    Main Spine 경유점을 Agent 3용 자연어 요약으로 변환.
    좌표 수치는 전달하지 않음 — 방향과 구조만 서술.
    """
    artery = space_data.get("fire", {}).get("main_artery")
    if not artery or not hasattr(artery, "coords"):
        return "주동선 정보 없음"

    coords = list(artery.coords)
    if len(coords) < 2:
        return "주동선 정보 없음"

    # 경유점 추출 (방향 전환점)
    turns = [coords[0]]
    for i in range(1, len(coords) - 1):
        px, py = coords[i - 1]
        cx, cy = coords[i]
        nx_, ny = coords[i + 1]
        cross = (cx - px) * (ny - cy) - (cy - py) * (nx_ - cx)
        if abs(cross) > 0.01:
            turns.append(coords[i])
    turns.append(coords[-1])

    # 바닥 bounds 기준 상대 위치 서술
    floor = space_data.get("floor", {})
    poly = floor.get("polygon")
    if poly:
        minx, miny, maxx, maxy = poly.bounds
    else:
        minx, miny, maxx, maxy = 0, 0, 100000, 100000

    width = maxx - minx
    height = maxy - miny

    def _describe_pos(x: float, y: float) -> str:
        """좌표를 상대 위치 서술로 변환."""
        rx = (x - minx) / width if width > 0 else 0.5
        ry = (y - miny) / height if height > 0 else 0.5
        h = "좌측" if rx < 0.33 else ("중앙" if rx < 0.66 else "우측")
        v = "상단" if ry < 0.33 else ("중간" if ry < 0.66 else "하단")
        return f"{v} {h}"

    lines = [f"입구에서 매장 가장 깊은 벽면 중앙까지 직각 주동선이 깔려 있습니다."]
    lines.append(f"경유점 {len(turns)}개:")
    for i, (x, y) in enumerate(turns):
        label = "입구" if i == 0 else ("종점(Deep Wall 중앙)" if i == len(turns) - 1 else f"꺾임점{i}")
        pos = _describe_pos(x, y)
        lines.append(f"  [{i}] {label} — {pos}")

    # 구간별 방향 서술
    for i in range(len(turns) - 1):
        sx, sy = turns[i]
        ex, ey = turns[i + 1]
        dx = ex - sx
        dy = ey - sy
        if abs(dx) < abs(dy) * 0.1:
            direction = "아래로 직진" if dy > 0 else "위로 직진"
        elif abs(dy) < abs(dx) * 0.1:
            direction = "오른쪽으로 직진" if dx > 0 else "왼쪽으로 직진"
        else:
            direction = "대각선 이동"
        lines.append(f"  구간 {i}→{i+1}: {direction}")

    lines.append("핵심 기물은 이 주동선이 지나는 구역(인접 벽면/슬롯)에 우선 배치하세요.")
    lines.append("기물 정면(direction)은 주동선을 향해야 합니다.")
    return "\n".join(lines)


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
