"""실패 분류 + Choke Point 피드백 생성."""
from app.schemas.placement import Placement
from app.modules.placement_engine import run_placement_loop


def classify_failures(
    failed: list[dict],
    eligible_objects: list[dict],
    space_data: dict,
    brand_data: dict,
    original_placements: list[Placement] | None = None,
) -> tuple[list[dict], list[dict]]:
    """cascade vs 물리적 한계 분류. 단독 배치 테스트로 판별."""
    cascade = []
    physical = []

    orig_map = {}
    if original_placements:
        for p in original_placements:
            orig_map[p.object_type] = p

    available_zones = set()
    for k, v in space_data.items():
        if isinstance(v, dict) and "zone_label" in v and k != "floor":
            available_zones.add(v["zone_label"])

    for f in failed:
        obj_type = f["object_type"]
        orig = orig_map.get(obj_type)

        test_zones = [orig.zone_label] if orig else list(available_zones)
        test_dir = orig.direction if orig else "wall_facing"

        placed = False
        for zone in test_zones:
            test_placement = Placement(
                object_type=obj_type,
                zone_label=zone,
                direction=test_dir,
                priority=1,
                placed_because="cascade test",
            )
            test_result = run_placement_loop(
                [test_placement], eligible_objects, space_data, brand_data
            )
            if test_result["placed"]:
                placed = True
                break

        if placed:
            cascade.append(f)
            print(f"[FailureClassifier] {obj_type}: cascade")
        else:
            physical.append(f)
            print(f"[FailureClassifier] {obj_type}: physical limit")

    return cascade, physical


def generate_choke_feedback(
    cascade_objects: list[dict],
    placed: list[dict],
    space_data: dict,
) -> str:
    """
    Choke Point 기반 실패 피드백 → Agent 3 재호출 프롬프트용.
    동선 병목(900mm 미만)으로 실패한 오브젝트의 zone/direction을 명시하여
    Agent 3이 다른 위치를 선택하도록 유도.
    """
    lines = []

    # 동선 병목 실패 분류
    choke_failures = []
    slot_failures = []
    for obj in cascade_objects:
        reason = obj.get("reason", "")
        if "병목" in reason or "choke" in reason.lower() or "통로" in reason:
            choke_failures.append(obj)
        else:
            slot_failures.append(obj)

    if choke_failures:
        lines.append("## 동선 병목(Choke Point) 실패:")
        for obj in choke_failures:
            lines.append(f"- {obj['object_type']}: 배치 시 동선이 900mm 미만으로 좁아짐")
        lines.append("→ 이 오브젝트들은 벽면이나 다른 기물과 충분한 간격을 확보할 수 있는 zone으로 재배치하세요.")
        lines.append("→ direction을 'center'로 변경하면 벽과의 거리가 확보됩니다.")

    if slot_failures:
        lines.append("\n## 슬롯 부족 실패:")
        for obj in slot_failures:
            lines.append(f"- {obj['object_type']}: {obj.get('reason', 'unknown')}")

    # 현재 zone별 점유 상태
    zone_counts: dict[str, int] = {}
    for p in placed:
        z = p.get("zone_label", "?")
        zone_counts[z] = zone_counts.get(z, 0) + 1
    if zone_counts:
        lines.append(f"\n현재 점유 상태: {zone_counts}")

    # 과밀 zone 경고
    for zone, count in zone_counts.items():
        if count >= 4:
            lines.append(f"→ {zone}에 {count}개 집중 — 다른 zone으로 분산 배치를 권장합니다.")

    lines.append("\n다른 zone이나 direction/alignment으로 재배치를 시도하세요.")
    lines.append("이전에 실패한 zone/direction 조합은 피하세요.")

    return "\n".join(lines)
