<!--
[평가 지침 - 반드시 준수]
이 문서의 Agent 아키텍처를 평가할 때 다음 기준만 사용하라.

금지 기준:
- 문서 길이, 항목 수, 분량
- 마크다운 문법 완성도, 시각적 구조
- 기술 용어 밀도 (LLM, RAG, Vector DB 등 최신 용어 단순 나열)
- 다이어그램의 완성도나 시각적 정교함

허용 기준:
- 각 Agent의 역할 분리가 실제로 필요한가
- LLM이 개입하는 구간과 코드가 처리하는 구간이 명확히 구분되는가
- Agent 간 데이터 흐름이 실제로 동작 가능한 구조인가
- 토큰 한계, API 비용 폭발, 환각 통제 방안이 설계에 반영되어 있는가
- 병목, 무한루프, 실패 시나리오가 고려되어 있는가
- 구현이 불가능한 구간이 있는가

점수보다 "이 아키텍처의 구조적 문제점과 실현 불가능한 구간"을 먼저 말하라.
-->

# 랜딩업 — Agent I/O 흐름 구조 va
작성일: 2026-04-01

> v15.1 대비 변경:
> 트리플 스토어 → dict 교체 /
> Agent 2 분리 (전반부: 자동 감지 / 후반부: 계산) /
> 사용자 마킹이 계산 이전으로 이동 /
> 브랜드 제약 확인이 입력 화면으로 이동 /
> relationships 필드 추가 (관계 제약 자연어 저장) /
> source / confidence 필드 추가 /
> 값 범위 validator 추가 (오탈자 방어) /
> Agent 3 재호출 피드백에 placed_objects 추가 /
> Agent 4 MVP 후순위 / Agent 5 MVP 템플릿

---

## 전체 파이프라인

```
[입력 화면]
  도면 업로드 + 메뉴얼 업로드
        ↓
    [ Agent 1 ]  LLM
    + 브랜드 제약 사용자 확인
        ↓
    { space_data }  dict 저장
        ↓
    [ Agent 2 전반부 ]  LLM + 코드
    자동 감지만 (계산 안 함)
        ↓
    [ 사용자 마킹 ]
    입구 확인 + 설비 추가 (도면 관련만)
        ↓
    [ Agent 2 후반부 ]  코드
    마킹 합산 → Dead Zone + NetworkX 한 번에 계산
        ↓
    { space_data }  dict 저장 완료
        ↓
    [ 1단계 확인 ]
    계산 결과 확인만 → "진행" or "처음부터 수정"
        ↓
    [ 오브젝트 선별 모듈 ]  코드
        ↓
    [ Agent 3 ]  LLM
        ↓  ← Pydantic 검증
    [ Shapely + NetworkX ]  코드
        ↓  ← 실패 시 코드 조정 → 그래도 실패 시 Agent 3 재호출
    [ 검증 모듈 ]  코드
        ↓
    [ .glb 생성 ]  코드
        ↓
    [ Agent 4 ]  LLM (MVP 후순위)
        ↓
    [ Agent 5 ]  템플릿 (MVP) → LLM (이후)
```

---

## 핵심 설계 원칙

```
LLM은 수학 계산을 하지 않는다.
LLM은 방향과 우선순위만 결정한다.
수치는 전부 Shapely/NetworkX가 계산하고 dict에 저장한다.
Agent 3은 자연어 요약만 읽고, 수치는 출력할 수 없다.
Shapely는 Agent 3 출력의 키이름으로 dict에서 원본 수치를 직접 조회한다.
배치와 통로 검증은 오브젝트 단위로 동시에 수행된다.
Agent 3 재호출은 코드 레벨 위치 조정이 불가한 경우에만 발생한다.
```

---

## 입력 화면

도면과 메뉴얼을 동시에 받고, Agent 1 실행 후 브랜드 제약 확인까지 처리.

```
도면 업로드: floor_plan.pdf
메뉴얼 업로드: brand_guide.pdf
"설비(스프링클러, 소화전 등)가 표시된 도면을 업로드해주세요."

→ [업로드] → Agent 1 실행 → 추출 결과 표시

  clearspace_mm: 1500mm         ✅ 확인 / ✏️ 수정
  금지 소재: 금속                ✅ 확인 / ✏️ 수정
  방향 규정: 입구 정면           ✅ 확인 / ✏️ 수정
  로고 여백: 미추출 → 기본값     ✅ / ✏️
  관계 규정: "라이언과 춘식이 떨어뜨릴 것"  ✅ / ✏️

[다음] → Agent 2 시작
```

이유: 브랜드 제약은 도면과 무관한 정보. 도면 마킹 단계에 섞으면 관심사가 뒤섞임.

---

## Agent 1 — 브랜드/기준법 수치 추출 [LLM]

### Input

```
브랜드 메뉴얼 PDF (Claude Document API)
```

### Output → dict 저장

```python
space_data["brand"] = {
    "clearspace_mm": {"value": 1500, "confidence": "high", "source": "manual"},
    "character_orientation": {"value": "입구 정면", "confidence": "high", "source": "manual"},
    "prohibited_material": {"value": "금속", "confidence": "medium", "source": "manual"},
    "logo_clearspace_mm": {"value": None, "confidence": None, "source": None},
    "relationships": [
        {"rule": "라이언과 춘식이를 떨어뜨릴 것", "confidence": "high"}
    ]
}

# null → 기본값 merge
DEFAULTS = {"clearspace_mm": 1000, "logo_clearspace_mm": 500}

# 소방법/시공기준 — 하드코딩 (법 고정값)
space_data["fire"] = {
    "main_corridor_min_mm": 900,
    "emergency_path_min_mm": 1200,
}
space_data["construction"] = {
    "wall_clearance_mm": 300,
    "object_gap_mm": 300,
}
```

### 추출 전략

추출 대상 (이것만 뽑음):
  1. clearspace_mm (여백 / 이격 / 띄움 / 여유 공간) → mm 통일
  2. character_orientation (배치 방향 / 정면 / 향하도록) → 정규화
  3. prohibited_material (금지 소재 / 사용 불가) → 소재명
  4. logo_clearspace_mm (로고 여백 / 로고 주변) → mm 통일
  5. relationships (관계 제약 — 수치 없는 규정) → 자연어 그대로

프롬프트 규칙:
  - 캐릭터명/IP명/마스코트명 → 모두 character_bbox로 간주
  - 이름을 몰라도 "조형물", "피규어", "스탠딩" 등 배치 대상 고유명사 → character_bbox
  - 동의어 처리 ("이격" = "띄움" = "여백" = "멀리")
  - 문서에 없으면 null (추측 금지)
  - confidence(high/medium/low) 같이 반환

### 값 범위 validator (오탈자 방어)

```python
class BrandConstraints(BaseModel):
    clearspace_mm: int

    @validator("clearspace_mm")
    def check_range(cls, v):
        if v < 300 or v > 5000:
            raise ValueError(f"clearspace {v}mm는 비정상 범위")
        return v
```

### 이유

- Agent 2 후반부에서 Shapely가 Dead Zone 계산할 때 wall_clearance_mm 등을 파라미터로 씀. 이 숫자 없으면 계산 불가
- 소방법/시공기준은 법 고정값이라 하드코딩. 단, 소화전/스프링클러 위치는 도면마다 다르므로 Agent 2에서 감지
- 자연어 해석 + 동의어 처리 + 단위 변환이 LLM의 강점. 코드로는 불가
- Sonnet으로 충분 (항목 4~5개, 파이프라인에서 1회 호출, 건당 100~200원)

### 가능/불가능

```
✅ 가능:
  - 텍스트 PDF 수치 추출
  - 이미지 PDF Vision 읽기
  - 동의어 처리 ("이격" = "띄움" = "여백")
  - 단위 변환 (cm/m → mm)
  - 무명 캐릭터 처리 (문맥 기반 판별)
  - 관계 제약 자연어 추출

⚠️ 주의:
  - 오탈자 → 값 범위 validator 방어
  - confidence low → 사용자 확인
  - "적절히" 같은 표현 → null → 기본값

❌ 불가능:
  - 문서에 안 적힌 제약 → 기본값
  - 저해상도 이미지 표 → OCR 실패 가능
  - 메뉴얼 없음 → 전부 기본값
```

---

## Agent 2 전반부 — 자동 감지 [LLM + 코드]

### Input

```
도면 이미지/PDF + Agent 1 dict
```

### 처리

1. OpenCV → 바닥 polygon 추출 (픽셀)
2. OCR → 치수선 읽어서 mm 변환 스케일 계산
3. Claude Vision → 입구 + 스프링클러 + 소화전 + 분전반 한 번에 감지

### Output → 임시 저장 (dict 확정 아님)

```python
auto_detected = {
    "floor_polygon_px": [[0,0],[600,0],[600,400],...],
    "scale_mm_per_px": 10.0,
    "scale_confidence": 0.95,
    "entrance": {"x_px": 0, "y_px": 100, "confidence": "high"},
    "sprinklers": [
        {"x_px": 150, "y_px": 200, "confidence": "high"}
    ],
    "fire_hydrant": [],
    "electrical_panel": [],
}
```

### 이유

여기서 Dead Zone 계산 안 하고 멈추는 이유: 소화전 위치를 모르는 상태에서 Dead Zone 만들면 → 사용자가 소화전 찍으면 → 재계산 필요. 전부 모은 다음에 한 번에 계산이 맞음.

### 가능/불가능

```
✅ 가능:
  - 벡터 PDF / CAD PDF 도면 polygon 추출
  - 치수선 스케일 자동 계산
  - 표준 건축 기호 감지 (스프링클러 ○+S 등)
  - 텍스트 설비 ("소화전" 글자) 감지
  - 입구 (문 기호, 화살표, "입구" 텍스트)

⚠️ 주의:
  - OCR 실패 → scale_confidence 낮음 → 사용자 직접 입력
  - 비표준 설비 기호 → confidence low

❌ 불가능:
  - 설비 표기 없는 도면 → 사용자 마킹으로 넘김
  - 스캔 품질 낮은 도면 → polygon 추출 실패 가능
  - 3D 도면 → 2D 평면도만 지원
```

---

## 사용자 마킹

### 화면

```
[도면 위에 오버레이]

감지 결과:
  ✅ 입구 — 자동 감지 (드래그 수정 가능)
  ✅ 스프링클러 2개 — 자동 감지 (드래그 수정 가능)

미감지:
  ❓ 소화전 — "위치를 알면 클릭해서 표시해주세요"
  ❓ 분전반 — "위치를 알면 클릭해서 표시해주세요"

[확정]  [모르겠음 — 설비 없이 진행]
```

### 처리

```python
# 사용자가 소화전 찍으면
auto_detected["fire_hydrant"].append({
    "x_px": 320, "y_px": 150, "confidence": "user_input"
})

# "모르겠음" 선택하면
auto_detected["disclaimer"] = ["fire_hydrant", "electrical_panel"]

# 자동 감지 수정하면
auto_detected["entrance"]["x_px"] = 50
auto_detected["entrance"]["confidence"] = "user_corrected"
```

### 이유

이 단계에서 도면 관련 모든 입력 확정. 이후는 사용자 입력 없이 계산만. 브랜드 확인은 입력 화면에서 이미 끝남 → 여기는 도면 관련만.

---

## Agent 2 후반부 — Dead Zone + 기준점 + NetworkX [코드]

### Input

```
auto_detected (사용자 수정 반영 완료) + Agent 1 dict
```

### 처리

1. 픽셀 → mm 변환 (스케일 적용)
2. Shapely → Dead Zone 생성 (자동 감지 + 사용자 마킹 전부 포함)
3. Shapely → reference_point 좌표 계산
4. NetworkX → 격자 그래프 + 보행 거리 계산
5. 자연어 요약 생성 (Agent 3용)

### Output → dict 저장 (두 형태로 확정)

```python
# ── 코드용 (수치) ──
space_data["floor"]["polygon"] = [[0,0],[6000,0],[6000,4000],...]
space_data["floor"]["usable_area_sqm"] = 22.4
space_data["floor"]["max_object_w_mm"] = 2400
space_data["entrance"]["x_mm"] = 0
space_data["entrance"]["y_mm"] = 1000
space_data["north_wall_mid"]["x_mm"] = 2300
space_data["north_wall_mid"]["y_mm"] = 3800
space_data["sprinkler_1"]["center_mm"] = [1500, 2000]
space_data["sprinkler_1"]["radius_mm"] = 2300
space_data["fire_hydrant_1"]["center_mm"] = [3200, 1500]  # 사용자 마킹
space_data["fire_hydrant_1"]["radius_mm"] = 1000

# ── Agent 3용 (자연어 요약) ──
space_data["entrance"]["zone_label"] = "entrance_zone"
space_data["north_wall_mid"]["zone_label"] = "mid_zone"
space_data["north_wall_mid"]["shelf_capacity"] = 3
space_data["inner_corner"]["zone_label"] = "deep_zone"

# ── 면책 항목 ──
space_data["infra"]["disclaimer"] = ["electrical_panel"]
```

### 이유: 두 형태 분리 저장

같은 데이터를 소비자에 따라 분리:
- Shapely: x_mm, y_mm → 좌표 계산에 사용
- Agent 3: zone_label, shelf_capacity → 판단에 사용

Agent 3에게 좌표를 안 보여주는 이유: 수치를 주면 LLM이 판단 넘어서 좌표 계산까지 함. 실패 시 LLM 재호출 = 돈 + 3~5초. 키이름만 받으면 코드가 0.01초에 위치 조정. 성공할 때 차이 없고, 실패할 때 차이 남.

관계 제약("떨어뜨릴 것" 등)은 수치가 아니므로 여기서 안 건드림. Agent 3 프롬프트에 그대로 전달.

---

## 1단계 사용자 확인

### 화면

```
[도면 위에 오버레이]
■ Dead Zone 3개 (스프링클러 2 + 소화전 1) — 빨간 영역
■ reference_points 5개 — 파란 점
■ 배치 가능 영역 — 초록 영역
■ 면책: 분전반 위치 미반영

[eligible_objects 미리보기]
character_bbox / shelf_rental / photo_zone

[진행]  [처음부터 수정]
```

이전 단계(사용자 마킹)와 차이: 마킹은 "입력", 여기는 "확인". 수정하면 마킹 단계로 돌아감.

---

## 오브젝트 선별 모듈 [코드]

### Input

```
dict (공간 수치) + Agent 1 dict (제약) + Supabase furniture_standards
```

### Output

```python
eligible_objects  # bbox 포함, 공간에 안 들어가는 것 / 브랜드 금지 제외
```

### 이유

Agent 3 이전에 하는 이유: 안 들어가는 오브젝트를 Agent 3이 배치하면 Shapely 실패 → 재호출 → 낭비. 미리 걸러두면 확실한 것만 판단.

---

## Agent 3 — 배치 의도 결정 [LLM]

### Input

```
자연어 요약만:
  "entrance: entrance_zone, walk 0mm"
  "north_wall_mid: mid_zone, shelf 3개 수용 가능"
  "inner_corner: deep_zone"
+ eligible_objects 목록
+ 관계 제약: "라이언과 춘식이를 떨어뜨릴 것"
+ "좌표·mm값 출력 금지"
+ 허용 reference_point 키 목록 (동적 생성)
```

### Output (Pydantic 강제)

```json
{
  "placements": [
    {
      "object_type": "character_bbox",
      "reference_point": "entrance",
      "direction": "inward",
      "priority": 1,
      "placed_because": "브랜드 메뉴얼 캐릭터 입구 정면 규정"
    },
    {
      "object_type": "shelf_rental",
      "reference_point": "north_wall_mid",
      "direction": "wall_facing",
      "priority": 2,
      "placed_because": "주력 진열 — mid_zone, 동선 방해 최소"
    }
  ]
}
```

### Pydantic 역할

스키마에 수치 필드 없음 → 좌표 출력 구조적 불가.
- direction: 허용 4개 중 아님 → 실패
- reference_point: 허용 키 목록에 없음 → 실패
- priority: int 아님 → 실패
- x_mm 같은 필드: 스키마에 없음 → 무시

형태 강제. 값의 정확성은 Shapely에서 잡힘.

Circuit Breaker: Pydantic 실패 → LLM 재호출 (최대 3회) → 3회 실패 시 파이프라인 중단.

### 이유

LLM이 잘하는 것: 공간 배치 판단 ("캐릭터는 입구 앞이 낫다"), 관계 제약 반영 ("떨어뜨릴 것" → 다른 위치에 배치).
LLM이 못하는 것: 정확한 수치 계산. 잘하는 것만 시키고 못하는 건 코드한테.

### 가능/불가능

```
✅ 가능:
  - zone 정보 기반 배치 판단
  - 관계 제약 반영
  - 브랜드 규정 반영
  - priority 결정

⚠️ 주의:
  - 오브젝트 수 많으면 판단 품질 저하 → 선별 모듈이 미리 줄여줌
  - 애매한 관계 제약은 해석 다를 수 있음 → placed_because로 추적

❌ 불가능:
  - 정확한 좌표 계산 (구조적 차단)
  - 물리적 충돌 판단 (Shapely 영역)
  - 통로 폭 계산 (NetworkX 영역)
```

---

## Shapely 배치 계산 + 증분 NetworkX 검증 [코드]

### Input

```python
# Agent 3: "shelf를 north_wall_mid에 wall_facing으로"
x = space_data["north_wall_mid"]["x_mm"]   # → 2300
y = space_data["north_wall_mid"]["y_mm"]   # → 3800
```

### 오브젝트별 루프

```
배치 → Shapely 충돌 체크 → NetworkX 통로 체크
  둘 다 통과 → 확정 → 다음
  실패 → 코드가 100mm씩 위치 조정 (0.01초)
    조정 성공 → 확정
    조정 실패 → Agent 3 재호출 (최대 2회)
```

### Agent 3 재호출 피드백

```python
feedback = {
    "failed_object": "photo_zone",
    "failed_reference_point": "inner_corner",
    "reason": "corridor_blocked",
    "max_available_w_mm": 1200,
    "placed_objects": [
        {"object_type": "character_bbox", "reference_point": "entrance"},
        {"object_type": "shelf_rental", "reference_point": "north_wall_mid"}
    ],
    "alternative_references": [
        {"key": "south_wall_mid", "zone_label": "mid_zone"}
    ]
}
```

placed_objects 이유: 없으면 Agent 3이 점유된 reference_point에 또 배치 → 실패 → 재호출 → Circuit Breaker 소진.

### 이유

- 한꺼번에 안 놓는 이유: 5개 다 놓고 "3번이 통로 막음" → 전부 다시. 하나씩 하면 1,2번 살리고 3번만 조정
- 코드가 먼저 조정하는 이유: API 호출 = 돈 + 3~5초. 코드 조정 = 0.01초

### 가능/불가능

```
✅ 가능:
  - 정확한 좌표 계산 (dict 직접 조회)
  - Dead Zone / 기배치 오브젝트 충돌 체크
  - 통로 폭 검증 (NetworkX 격자)
  - 코드 레벨 위치 조정

⚠️ 주의:
  - step_mm / max_steps 튜닝 필요 → 스프린트 2 초기값, 스프린트 5 재조정
  - 비정형 도면 → reference_point 계산 복잡도 증가

❌ 불가능:
  - 감성 판단 ("예뻐 보이는지")
  - 3D 높이 간섭 체크 (2D Shapely 한계)
```

---

## 검증 모듈 [코드]

### Input

```
layout_objects + Dead Zone + 최종 그래프 + 소방 기준
```

### Output

```
blocking → .glb 출력 차단 + 사용자 알림
그 외    → .glb 정상 출력
```

MVP에서는 blocking이면 차단, 아니면 통과.

---

## .glb 생성 [코드]

```
layout_objects → Three.js Whitebox 3D → .glb export
SketchUp Pro에서 열림
높이는 DB에 저장된 값 사용 (shelf 1200mm, character 2000mm 등)
높이 간섭은 SketchUp에서 확인 필요 (리포트에 기재)
```

---

## Agent 4 — 레이아웃 검토 [LLM] (MVP 후순위)

스크린샷 보고 브랜드 규정 감성 검토. Shapely가 수치로 다 잡으니까 MVP에서는 사람이 SketchUp에서 확인.

---

## Agent 5 — 리포트 [템플릿] (MVP)

dict + Agent 3 출력 + 검증 결과에 정보가 전부 있으므로 템플릿에 값 끼워넣기.

source별 표기:
```
clearspace_mm: 1500mm (브랜드 메뉴얼 추출)
logo_clearspace_mm: 500mm (기본값 — 메뉴얼에 명시 없음)
소화전: 사용자 입력
분전반: 미반영 (면책)
```

면책 조항은 space_data["infra"]["disclaimer"]에서 자동 삽입.

---

## 데이터 흐름 요약

```
수치 제약 → dict에 숫자 → 코드(Shapely/NetworkX)가 계산
관계 제약 → dict에 자연어 → Agent 3이 판단
```

## 역할 분리

```
LLM: 자연어 해석, 동의어 처리, 배치 판단, 관계 제약 반영
코드: 좌표 계산, 충돌 검증, 통로 검증, 위치 조정
```

## 실패 처리

```
추출 실패 → null → 기본값 + source 추적
감지 실패 → 사용자 마킹 + 면책 조항
배치 실패 → 코드 조정(0.01초) → 안 되면 Agent 3 재호출(최대 2회)
스키마 실패 → Circuit Breaker 3회 → 파이프라인 중단
```

## v15.1 대비 변경 사항

```
[변경] 트리플 스토어 → dict
[변경] Agent 2 분리 (전반부: 감지 / 후반부: 계산)
[변경] 사용자 마킹이 계산 이전으로 이동
[변경] 브랜드 확인이 입력 화면으로 이동
[변경] 1단계 확인은 결과 확인만
[추가] relationships 필드 (관계 제약 자연어 저장)
[추가] source / confidence 필드 (추적용)
[추가] 값 범위 validator (오탈자 방어)
[추가] placed_objects 피드백 (재호출 시 점유 현황)
[유지] LLM은 판단만, 코드는 계산
[유지] 증분 검증 + 코드 우선 조정
[유지] Agent 4 MVP 후순위
[유지] Agent 5 MVP 템플릿
```
