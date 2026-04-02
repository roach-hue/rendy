# LandingUp 아키텍처 업데이트 — Gemini 전달용
작성일: 2026-04-01

기존 va 아키텍처 대비 오늘 확정된 변경 사항 및 논의 결과 전달.

> 전체 논의 흐름, 선택지별 기각 이유는 **architecture_decisions.md** 참조.

---

## 기존 va 대비 변경 항목

### 1. Agent 1 — Regex 전처리 hybrid 추가

**변경 이유**: LLM이 400mm를 4000mm로 환각해도 값 범위(300~5000) validator 통과 가능. 사용자 확인 UI는 fallback이지 시스템 해결책 아님.

**확정**:
- 텍스트 PDF → Python Regex로 숫자/단위 기계 추출 → LLM은 라벨링(어떤 규정인지)만 수행
- 이미지 PDF → Claude Vision 유지

---

### 2. Agent 2 후반부 — space_data 필드 추가

**변경 이유**: calculate_position 함수가 벽 방향과 벽 표면 좌표를 알아야 polygon 계산 가능. 추론이 아니라 명시적 저장.

**확정**:
```python
space_data["north_wall_mid"]["wall_normal"] = "south"   # 벽 앞면이 향하는 방향
space_data["north_wall_mid"]["wall_surface_y"] = 4000   # 실제 벽 표면 좌표
```

---

### 3. calculate_position 함수 신설

**변경 이유**: Agent 3 direction 출력을 실제 polygon 좌표로 변환하는 로직이 Shapely 단계에 암묵적으로 묻혀 있었음. 명시적 함수로 분리.

**확정**:
- 코드 순회 루프 안에서 placement_slot마다 실행
- 모서리 4개는 함수 내부에서 중심점 + width/2, depth/2 조합으로 계산

**direction별 계산 규칙**:

| direction | 중심점 계산 | 회전각 |
|---|---|---|
| wall_facing | placement_slot.x, wall_surface에서 depth/2 띄움 | wall_normal 반대 방향 |
| inward | placement_slot.x, placement_slot.y | entrance 좌표를 향하는 각도 |
| outward | placement_slot.x, placement_slot.y | entrance 반대 방향 |
| center | placement_slot.x, placement_slot.y | floor center 좌표를 향하는 각도 |

⚠️ 실제 도면 테스트 검증 필수. 비정형 도면 엣지케이스 오작동 가능성 있음.

---

### 4. Agent 3 output — zone_label 통일

**변경 이유**: 기존에는 Agent 3이 placement_slot를 직접 지정했음. 위치 탐색을 코드로 넘기기 위해 zone_label만 출력하도록 변경.

**확정**:
- Agent 3은 항상 zone_label만 출력 (placement_slot 출력 금지)
- Union 타입 채택 안 함 — target_type 오태깅 버그 위험
- 소형/대형 공간 구분 없이 동일 스키마

**변경된 Pydantic 스키마**:
```python
class Placement(BaseModel):
    object_type: str
    zone_label: str        # 기존 placement_slot → zone_label로 교체
    direction: Literal["wall_facing", "inward", "outward", "center"]
    priority: int
    placed_because: str
```

---

### 5. 배치 실패 처리 — 코드 순회로 Agent 3 재호출 최소화

**변경 이유**: 기존에는 배치 실패 시 바로 Agent 3 재호출. API 비용 + 지연 + 무한루프 위험.

**확정된 실패 처리 흐름**:

```
오브젝트 배치 시도
  └→ calculate_position
  └→ Shapely 충돌 + NetworkX 통로 동시 검증

실패 시:
→ 코드가 해당 zone 안의 placement_slot 전체 순회
   (attempt_placement: step_mm = bbox_w × 10% 초기값, zone 반경 초과 시 즉시 실패)

전부 실패 시:
→ 단독 배치 테스트 (빈 도면에 해당 오브젝트만)
  → 단독 실패 = 물리적 한계 → Graceful Degradation
  → 단독 성공 = cascade failure → Global Reset + 실패 컨텍스트 주입 → Agent 3 재호출
```

**Agent 3 재호출 무한루프 처리**:
- 재호출 시 실패한 zone을 컨텍스트에 누적해서 전달
- Agent 3이 시도 가능한 zone이 하나씩 줄어듦
- 모든 zone 소진 시 자연 종료 (zone 개수 = 최대 재호출 횟수)

**placed_because 처리**:
- Agent 3 기획 의도 보존
- 코드가 위치 조정한 경우: "1차 지정 위치(X) 공간 부족으로 인접 구역(Y) 자동 조정" 한 줄 추가

---

### 6. cascade failure 판정 기준 확정

**변경 이유**: 기존에는 2회 Global Reset 후 Graceful Degradation으로 넘어갔는데, 물리적 한계와 cascade failure를 구분하지 못했음.

**확정**:
```
placement_slot 전체 순회 전부 실패
→ 단독 배치 테스트 (빈 도면)
  → 단독 실패 = 물리적 한계 → Graceful Degradation (해당 오브젝트 drop)
  → 단독 성공 = 다른 오브젝트가 막음 = cascade failure → Global Reset
```

---

### 7. Graceful Degradation 추가 (신규)

**변경 이유**: 기존 설계에 공간 물리적 한계 처리 로직 없음.

**확정**:
- 단독 배치 테스트 실패 → 해당 오브젝트 drop
- 나머지 오브젝트로 재시도
- 최종 리포트: "배치 불가 오브젝트 목록 + 사유" 명시

---

## 기각된 제안

| 제안 | 기각 이유 |
|---|---|
| 사전 분석 레이어 (Pre-analysis Layer) | 정확한 분석 = 본 배치와 동일 연산 낭비. 근사치는 LLM에 거짓 정보 주입 |
| Targeted Removal (원인 오브젝트만 제거) | NetworkX는 결과(막힘)만 반환. 원인 역추적 불가 |
| step_mm / max_steps 하드코딩 | 공간/오브젝트 크기 무관한 고정값 부적합 |
| Union 타입 스키마 | target_type 오태깅 버그 위험 |
| Agent 3 output에 placement_slot 유지 | 위치 탐색을 LLM에 맡기면 API 비용 + 지연 발생 |
| CSP 브루트포스 + Agent 3 역할 축소 | placed_because 소멸 → 서비스 핵심 상품성 파괴 |

---

## 미결 사항 (실제 도면 테스트 후 결정)

| 항목 | 내용 |
|---|---|
| step_mm 비율 | bbox_w × 10% 초기값. 소형(200mm 이하) 과도한 루프 / 대형(2000mm 이상) 최적점 건너뜀 가능 — 테스트 후 조정 |
| 소형/대형 공간 기준선 | usable_area_sqm 기준 분기 수치 — 테스트 후 결정 |
