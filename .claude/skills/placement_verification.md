---
name: 배치 검증 스킬
description: 배치 완료된 레이아웃이 소방/시공 기준을 충족하는지 최종 검증하는 규칙
---

# 배치 검증 스킬 (Placement Verification Skill)

## 목적
코드 순회 루프에서 확정된 배치 결과가 소방/시공 법규 기준을 충족하는지 최종 검증. blocking 기준에 해당하면 .glb 출력 차단.

> ⚠️ 이 모듈은 순수 코드 — LLM 개입 없음

---

## blocking 기준

아래 조건 중 **하나라도 해당하면** .glb 생성 차단:

| 검증 항목 | 기준 수치 | 출처 |
|-----------|-----------|------|
| 소방 주통로 | 최소 900mm | `space_data["fire"]["main_corridor_min_mm"]` |
| 비상 대피로 | 최소 1200mm | `space_data["fire"]["emergency_path_min_mm"]` — 루프 내 Main Artery buffer(600)으로 proactive 보호됨. 최종 확인용. (Issue 19) |
| Dead Zone 침범 | 오브젝트 bbox가 Dead Zone과 교차 | Shapely intersects — 접면도 허용 불가 (Issue 20). 일반 오브젝트 간 충돌은 intersection().area > 0 사용. |

---

## 검증 프로세스

```
Step 1: 소방 주통로 검증
  → 입구에서 모든 구역까지의 경로에서 최소 폭 900mm 확보 여부
  → NetworkX 최종 그래프에서 경로 확인
  → 미달 시 blocking = True

Step 2: 비상 대피로 검증
  → 비상구까지의 경로에서 최소 폭 1200mm 확보 여부
  → 미달 시 blocking = True

Step 3: Dead Zone 침범 검증
  → 모든 확정 오브젝트의 bbox와 Dead Zone의 Shapely intersects 체크
  → 침범 시 blocking = True

Step 4: 벽체 이격 검증
  → 오브젝트와 벽면 간 최소 300mm 이격
  → space_data["construction"]["wall_clearance_mm"]
  → 미달 시 warning (blocking 아님)
```

---

## 검증 결과 출력

```python
verification_result = {
    "blocking": True,  # True면 .glb 차단
    "checks": [
        {
            "item": "main_corridor",
            "required_mm": 900,
            "actual_mm": 750,
            "passed": False,
            "detail": "shelf_3tier와 character_ryan 사이 통로 750mm"
        },
        {
            "item": "emergency_path",
            "required_mm": 1200,
            "actual_mm": 1500,
            "passed": True,
            "detail": ""
        },
        {
            "item": "dead_zone",
            "passed": True,
            "detail": ""
        },
        {
            "item": "wall_clearance",
            "required_mm": 300,
            "actual_mm": 250,
            "passed": False,
            "detail": "shelf_3tier 북벽 이격 250mm (warning only)"
        }
    ],
    "warnings": ["shelf_3tier 북벽 이격 250mm — 시공 기준 300mm 미달"]
}
```

---

## blocking vs warning 구분

| 구분 | 조건 | 결과 |
|------|------|------|
| **blocking** | 소방 통로/비상 대피로/Dead Zone | .glb 생성 차단 |
| **warning** | 벽체 이격 등 시공 권고 | .glb 생성 허용, 리포트에 경고 포함 |

---

## 주의사항

- blocking이 아니면 무조건 통과 — 추가 검증 삽입 금지
- 검증 결과는 Agent 5 리포트에 전달
- blocking 시 구체적 위반 항목과 수치를 명시 (어떤 오브젝트 간 통로가 몇 mm인지)
- 이 모듈은 배치 순회 루프의 buffer(450) 근사 검증과 별개 — 최종 확정 후 법규 기준 교차 검증
