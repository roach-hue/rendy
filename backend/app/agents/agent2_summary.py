"""Agent 3용 자연어 요약 생성."""
from collections import Counter


def make_agent3_summary(slots: dict[str, dict], space_data: dict) -> str:
    """
    Agent 3 프롬프트용 자연어 요약 문자열 생성.

    슬롯 수가 많을 때(>100) 전체 나열 대신 통계 요약 + 대표 슬롯 샘플로 토큰 절약.
    Agent 3은 zone_label + spine_rank + semantic_tags 조합으로 판단하므로
    개별 슬롯 좌표는 불필요.
    """
    lines = [
        f"총 배치 가능 면적: {space_data['floor'].get('usable_area_sqm', '?')}m²",
        f"천장 높이: {space_data['floor'].get('ceiling_height_mm', {}).get('value', 3000)}mm",
    ]

    total = len(slots)

    if total <= 100:
        # 소규모: 전체 나열
        lines.append("")
        lines.append("배치 슬롯 목록:")
        for key, slot in slots.items():
            lines.append(_format_slot(key, slot))
    else:
        # 대규모: 통계 요약 + 대표 샘플
        lines.append("")
        lines.append(f"총 슬롯: {total}개")

        # zone별 spine_rank 분포
        lines.append("")
        lines.append("zone × spine 분포:")
        dist: dict[str, Counter] = {}
        for slot in slots.values():
            zone = slot.get("zone_label", "unknown")
            rank = slot.get("spine_rank", "far")
            if zone not in dist:
                dist[zone] = Counter()
            dist[zone][rank] += 1
        for zone in ["entrance_zone", "mid_zone", "deep_zone"]:
            if zone in dist:
                parts = ", ".join(f"{r}={c}" for r, c in sorted(dist[zone].items()))
                lines.append(f"  {zone}: {parts}")

        # semantic_tags 분포
        tag_counts: Counter = Counter()
        for slot in slots.values():
            for tag in slot.get("semantic_tags", []):
                tag_counts[tag] += 1
        if tag_counts:
            lines.append("")
            lines.append("semantic_tags 분포:")
            for tag, count in tag_counts.most_common():
                lines.append(f"  {tag}: {count}개")

        # 대표 슬롯 샘플: 각 zone×spine_rank 조합에서 최대 3개
        lines.append("")
        lines.append("대표 슬롯 샘플 (각 zone×spine 조합별 최대 3개):")
        sampled = _sample_representative_slots(slots)
        for key, slot in sampled:
            lines.append(_format_slot(key, slot))

    return "\n".join(lines)


def _format_slot(key: str, slot: dict) -> str:
    """슬롯 한 줄 포맷."""
    tags = slot.get("semantic_tags", [])
    tag_str = f", tags=[{', '.join(tags)}]" if tags else ""
    spine_rank = slot.get("spine_rank", "")
    spine_str = f", spine={spine_rank}" if spine_rank else ""
    return (
        f"  {key}: {slot['zone_label']}, "
        f"walk_mm={slot['walk_mm']}, "
        f"선반 수용={slot['shelf_capacity']}개"
        f"{spine_str}"
        f"{tag_str}"
    )


def _sample_representative_slots(
    slots: dict[str, dict],
    per_group: int = 3,
) -> list[tuple[str, dict]]:
    """각 zone×spine_rank 조합에서 walk_mm 기준 균등 샘플."""
    groups: dict[str, list[tuple[str, dict]]] = {}
    for key, slot in slots.items():
        zone = slot.get("zone_label", "unknown")
        rank = slot.get("spine_rank", "far")
        group_key = f"{zone}_{rank}"
        if group_key not in groups:
            groups[group_key] = []
        groups[group_key].append((key, slot))

    sampled = []
    for group_key in sorted(groups.keys()):
        members = sorted(groups[group_key], key=lambda kv: kv[1].get("walk_mm", 0))
        if len(members) <= per_group:
            sampled.extend(members)
        else:
            # 균등 분할: 처음, 중간, 끝
            step = max(1, len(members) // per_group)
            for i in range(0, len(members), step):
                sampled.append(members[i])
                if len([s for s in sampled if s[0].startswith(group_key.split("_")[0])]) >= per_group:
                    break

    return sampled
