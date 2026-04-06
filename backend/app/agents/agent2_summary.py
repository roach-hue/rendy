"""Agent 3용 자연어 요약 생성."""


def make_agent3_summary(slots: dict[str, dict], space_data: dict) -> str:
    """Agent 3 프롬프트용 자연어 요약 문자열 생성."""
    lines = [
        f"총 배치 가능 면적: {space_data['floor'].get('usable_area_sqm', '?')}m²",
        f"천장 높이: {space_data['floor'].get('ceiling_height_mm', {}).get('value', 3000)}mm",
        "",
        "배치 슬롯 목록:",
    ]
    for key, slot in slots.items():
        tags = slot.get("semantic_tags", [])
        tag_str = f", tags=[{', '.join(tags)}]" if tags else ""
        lines.append(
            f"  {key}: {slot['zone_label']}, "
            f"walk_mm={slot['walk_mm']}, "
            f"선반 수용={slot['shelf_capacity']}개"
            f"{tag_str}"
        )
    return "\n".join(lines)
