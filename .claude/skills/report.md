---
name: 리포트 생성 스킬
description: Agent 5가 배치 결과를 f-string 템플릿으로 기계 조립하여 최종 리포트를 생성하는 규칙
---

# 리포트 생성 스킬 (Report Skill)

## 목적
배치 결과(dict + placements + 검증 결과)를 f-string 템플릿으로 기계 조립하여 최종 리포트 생성.

> ⚠️ LLM이 요약문을 생성하는 게 아니라 f-string 템플릿으로 기계 조립 — 수치 환각 원천 차단

---

## 리포트 포함 내용

### 1. source별 수치 표기

각 수치의 출처를 명시:

```
| 항목 | 값 | 출처 |
|------|-----|------|
| 이격 거리 | 1500mm | 브랜드 메뉴얼 추출 |
| 벽체 이격 | 300mm | 기본값 |
| 입구 위치 | (0, 100) | 사용자 입력 |
```

### 2. placed_because (Agent 3 기획 의도)

```
| 오브젝트 | 구역 | 기획 의도 |
|----------|------|-----------|
| character_ryan | mid_zone | 매장 중앙부에서 고객 시선 유도 |
| shelf_3tier | entrance_zone | 입구 진입 시 첫 상품 노출 |
```

### 3. 코드 조정 이력 (adjustment_log)

코드가 위치를 자동 조정한 경우 `placement.adjustment_log` 필드에서 읽어 반드시 기록:

```
shelf_3tier: 1차 지정 위치(north_wall_mid) 공간 부족으로 south_wall_left 자동 조정 (거리: 450mm)
```

> adjustment_log가 None이면 해당 오브젝트는 조정 없이 기획 의도대로 배치됨.

### 3-b. Deterministic Fallback 항목 (Issue 15)

Global Reset 2회 소진 후 코드가 강제 배치한 오브젝트는 별도 표기:

```
⚠️ 자동 배치 항목 (Agent 3 기획 아님):
| 오브젝트 | 배치 위치 | 사유 |
|----------|-----------|------|
| display_panel | east_wall | Global Reset 2회 소진 후 zone 제약 무시 자동 배치 |
```

> placed_objects의 `source: "fallback"` 항목은 반드시 이 섹션에 포함.

### 4. 배치 불가 오브젝트 목록 + 사유

```
| 오브젝트 | 사유 |
|----------|------|
| large_display | 물리적 한계: 단독 배치 테스트 실패 (오브젝트 크기 2000×1500mm, 가용 공간 부족) |
```

### 5. 면책 조항 (disclaimer)

```
⚠️ 면책 사항:
- electrical_panel: 분전반 위치가 확인되지 않았습니다. 시공 전 현장 확인이 필요합니다.
```

---

## 리포트 템플릿

```python
report_template = f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📊 LandingUp 배치 리포트
생성일: {datetime.now().strftime("%Y-%m-%d %H:%M")}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📌 공간 정보
- 가용 면적: {usable_area_sqm}m²
- 바닥 형상: {floor_shape_description}
- 입구: {entrance_description}

📦 배치 결과 ({placed_count}/{total_count}개 배치 완료)

{placement_table}

🔧 자동 조정 이력
{adjustment_log}

⚠️ 배치 불가 항목
{dropped_objects_table}

✅ 검증 결과
- 소방 주통로: {corridor_status}
- 비상 대피로: {emergency_status}
- Dead Zone: {deadzone_status}
{warnings}

📋 수치 출처
{source_table}

{disclaimer_section}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
```

---

## 검증 결과 표시 규칙

```
검증 통과:
  "✅ 소방 주통로: 통과 (최소 폭 1050mm, 기준 900mm)"

검증 미달 (blocking):
  "❌ 소방 주통로: 미달 (최소 폭 750mm, 기준 900mm) — .glb 생성 차단"

경고 (warning):
  "⚠️ 벽체 이격: 250mm (기준 300mm) — 시공 시 확인 필요"
```

---

## 출력 채널

| 채널 | 포맷 | 용도 |
|------|------|------|
| 웹 UI | 렌더링된 리포트 | 사용자 확인 |
| JSON | 구조화 데이터 | DB 저장 / API 응답 |
| 텍스트 | 플레인 텍스트 | 로깅 / 디버깅 |

---

## 주의사항

- 모든 수치는 space_data에서 직접 참조 — LLM이 수치를 생성하거나 해석하는 것 금지
- 리포트에 추측성 표현 금지 ("~일 수 있습니다", "~할 것으로 예상")
- disclaimer가 있으면 반드시 포함 — 생략 금지
- 배치 불가 오브젝트가 있으면 사유와 함께 반드시 명시 — 성공 건수만 보여주고 실패를 숨기는 것 금지
