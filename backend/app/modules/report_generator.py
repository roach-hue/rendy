"""
P0-7a — Agent 5 리포트 생성 (f-string 템플릿, LLM 아님)

배치 결과 + 검증 결과 → 디자이너 리뷰용 텍스트 리포트 기계 조립.
source별 표기, placed_because, adjustment_log, fallback 항목, disclaimer.
"""
from datetime import datetime


def generate_report(
    placed: list[dict],
    dropped: list[dict],
    verification: dict,
    space_data: dict,
    brand_data: dict,
    fallback_used: bool,
) -> str:
    """배치 결과 리포트 생성."""
    lines = []

    # 헤더
    lines.append("=" * 60)
    lines.append("LandingUp 배치 기획 리포트")
    lines.append(f"생성 시각: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append("=" * 60)
    lines.append("")

    # 공간 요약
    floor = space_data.get("floor", {})
    lines.append("## 공간 요약")
    lines.append(f"- 가용 면적: {floor.get('usable_area_sqm', '?')}m2")
    ceiling = floor.get("ceiling_height_mm", {})
    ch_val = ceiling.get("value", 3000) if isinstance(ceiling, dict) else 3000
    ch_src = ceiling.get("source", "default") if isinstance(ceiling, dict) else "default"
    lines.append(f"- 천장 높이: {ch_val}mm (source: {ch_src})")
    lines.append("")

    # 브랜드 제약 요약
    lines.append("## 브랜드 제약")
    for key in ["clearspace_mm", "logo_clearspace_mm", "character_orientation", "prohibited_material"]:
        field = brand_data.get(key, {})
        if isinstance(field, dict) and field.get("value") is not None:
            lines.append(f"- {key}: {field['value']} ({field.get('confidence', '?')} / {field.get('source', '?')})")
    pair_rules = brand_data.get("object_pair_rules", [])
    for r in pair_rules:
        rule_text = r.get("rule", r) if isinstance(r, dict) else str(r)
        lines.append(f"- 쌍 규정: {rule_text}")
    lines.append("")

    # 배치 결과
    lines.append(f"## 배치 결과 ({len(placed)}개 배치, {len(dropped)}개 드랍)")
    lines.append("")

    for i, p in enumerate(placed, 1):
        src = p.get("source", "agent3")
        lines.append(f"### {i}. {p['object_type']}")
        lines.append(f"- 위치: ({p['center_x_mm']}, {p['center_y_mm']})mm")
        lines.append(f"- 회전: {p['rotation_deg']}deg")
        lines.append(f"- 크기: {p['width_mm']}x{p['depth_mm']}mm")
        lines.append(f"- slot: {p.get('slot_key', '?')}")
        lines.append(f"- zone: {p.get('zone_label', '?')}")
        lines.append(f"- direction: {p.get('direction', '?')}")
        lines.append(f"- 배치 근거: {p.get('placed_because', '?')}")
        lines.append(f"- source: {src}")
        if p.get("adjustment_log"):
            lines.append(f"- 조정 이력: {p['adjustment_log']}")
        lines.append("")

    # 드랍 항목
    if dropped:
        lines.append("## 드랍된 오브젝트")
        for d in dropped:
            lines.append(f"- {d['object_type']}: {d.get('reason', '?')}")
        lines.append("")

    # 검증 결과
    lines.append("## 검증 결과")
    lines.append(f"- 판정: {'PASS' if verification.get('passed') else 'FAIL'}")
    for b in verification.get("blocking", []):
        lines.append(f"- [BLOCKING] {b['object_type']}: {b['detail']}")
    for w in verification.get("warning", []):
        lines.append(f"- [WARNING] {w['object_type']}: {w['detail']}")
    lines.append("")

    # fallback 표기
    if fallback_used:
        lines.append("## 주의사항")
        lines.append("- 일부 오브젝트가 Deterministic Fallback으로 강제 배치되었습니다.")
        lines.append("- source: 'fallback' 표기된 항목은 Agent 3 기획이 아닌 자동 배치입니다.")
        lines.append("- 디자이너 검토 후 위치 조정을 권장합니다.")
        lines.append("")

    # disclaimer
    lines.append("---")
    lines.append("본 리포트는 AI가 자동 생성한 초안입니다.")
    lines.append("최종 배치는 디자이너의 검토와 현장 확인이 필요합니다.")
    lines.append("소방 통로 규정(900mm/1200mm)은 관할 소방서 기준을 우선 적용하세요.")

    report = "\n".join(lines)
    print(f"[ReportGenerator] report generated: {len(lines)} lines")
    return report
