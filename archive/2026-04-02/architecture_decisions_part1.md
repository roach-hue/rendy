# Architecture Decisions — Part 1 (Issue 1-11)

> Part 2: architecture_decisions_part2.md (Issue 12-22 + 미결)

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

# LandingUp 아키텍처 의사결정 기록
작성일: 2026-04-01

---

## Issue 1. Agent 1 — LLM 환각으로 인한 수치 오류

**문제**: PDF에서 400mm를 4000mm로 잘못 읽어도 값 범위(300~5000) validator 통과 가능

| 선택지 | 내용 | 결과 |
|---|---|---|
| A | 사용자 확인 UI에서 사람이 시각으로 잡음 | 기각 — fallback이지 시스템 해결책 아님 |
| B | Regex 전처리 hybrid (텍스트 PDF는 Regex로 수치 추출, LLM은 라벨링만) | **채택** |

**결정**: 텍스트 PDF → Regex 기계 추출 → LLM 라벨링. 이미지 PDF → Claude Vision 유지.

---

## Issue 2. step_mm / max_steps 기준

**문제**: attempt_placement가 위치 조정 시 이동 보폭과 최대 시도 횟수 기준 없음

| 선택지 | 내용 | 결과 |
|---|---|---|
| A | 50~100mm, 10회 이하 하드코딩 (Gemini 원안) | 기각 — 공간 크기 무관하게 고정값은 부적합 |
| B | space_data 기반 동적 계산 (bbox_w 비율, zone 반경 기준) | **채택** |

**결정**: step_mm = bbox_w × 비율 (비율 수치 미결). max_steps = zone 반경 / step_mm. attempt_placement 목적은 미세 회피이므로 zone 반경 초과 시 즉시 실패 선언.

---

## Issue 3. Cascade Failure 처리

**문제**: 상위 오브젝트가 유일한 통로를 선점하면 하위 오브젝트 배치 불가. Greedy 구조적 한계.

| 선택지 | 내용 | 결과 |
|---|---|---|
| A | placed_objects 유지 + alternative_references 풀 확장 | 기각 — 근본 원인(상위 선점) 해결 불가 |
| B | Targeted Removal: 원인 오브젝트만 제거 | 기각 — NetworkX는 결과(막힘)만 반환, 원인 역추적 불가 |
| C | Global Reset + 실패 컨텍스트 주입 후 Agent 3 재호출 | **채택** |

**결정**: 배치 실패 시 도면 전체 초기화. Agent 3 재호출 시 "A+B 조합이 통로를 막았다"는 실패 맥락 포함. 단, 동일 reasoning 반복 → 무한루프 가능성은 Issue 15 (Deterministic Fallback)에서 해소됨.

---

## Issue 4. 사전 분석 레이어 (Pre-analysis Layer)

**문제**: Agent 3이 미래 배치를 고려하지 않고 현재 최선만 판단하는 Greedy 한계 보완 목적으로 제안

| 선택지 | 내용 | 결과 |
|---|---|---|
| A | Agent 3 이전에 충돌 가능성 분석 레이어 추가, 자연어로 경고 주입 | **기각** |
| B | 없음 | 유지 |

**기각 이유**: 정확한 사전 분석 = 본 배치 연산과 동일한 Shapely+NetworkX 시뮬레이션 필요 (낭비). 가벼운 근사치(면적 합산)는 병목 구간 미감지 → LLM에 거짓 정보 주입. 자연어 조건문 증가 → 환각 확률 상승.

---

## Issue 5. 공간 물리적 한계 처리 (Graceful Degradation)

**문제**: 공간이 모든 오브젝트를 수용 불가한 경우 처리 로직 없음 (기존 설계 맹점)

| 선택지 | 내용 | 결과 |
|---|---|---|
| A | 없음 (기존) | 기각 |
| B | Auto-drop: 2회 Global Reset 후에도 실패 시 최하위 priority 오브젝트 드랍, 나머지로 재시도, 리포트에 명시 | **채택** |

**결정**: 물리적 한계 판정 후 priority 기반 자동 드랍. 최종 리포트에 "배치 불가 오브젝트 목록 + 사유" 포함. Cascade Failure(배치 순서 문제)와는 별개 케이스.

---

---

## Issue 6. calculate_position 함수 스펙

> ⚠️ **SUPERSEDED**: wall 표현 방식이 Issue 8에서 LineString으로 교체됨. `wall_surface_y` 단일 좌표 방식 폐기. **Issue 8을 기준으로 구현할 것.**

**확정된 구조 (Issue 8 교체 전 기록 보존용)**:
- `calculate_position`은 명시적 함수로 분리
- 모서리 4개는 함수 내부에서 중심점 + width/2, depth/2 조합으로 계산 후 Shapely polygon 생성
- 코드 순회 루프 안에서 placement_slot마다 실행

**direction별 중심점 계산 — 미결 사항 포함**:

| direction | 중심점 계산 | 회전각 | 상태 |
|---|---|---|---|
| wall_facing | Issue 8 (LineString + 수선의 발)으로 교체 | wall_normal 반대 방향 | Issue 8 참조 |
| inward | placement_slot에서 entrance 방향으로 오프셋 필요 — 규칙 미결 | entrance 좌표를 향하는 각도 | **미결** |
| outward | 더미 처리 — 실제 사용 케이스 없음. 추후 케이스 확인 시 추가 | — | **비활성** |
| center | placement_slot에서 floor center 방향으로 오프셋 필요 — 규칙 미결 | floor center 좌표를 향하는 각도 | **미결** |

**⚠️ 오류 수정**: inward/center 중심점을 `placement_slot.x, placement_slot.y` 그대로 쓰면 오브젝트가 벽 안으로 파고들 수 있음. 방향별 오프셋 규칙 필요.

**outward 더미 처리 이유**: 캐릭터/조형물은 inward, 선반/가벽은 wall_facing, 포토존은 center로 커버됨. outward가 필요한 실제 오브젝트 케이스 없음.

---

---

## Issue 7. Global Reset 무한루프 + Agent 3 재호출 최소화

**문제**: cascade failure 시 Agent 3 재호출이 반복되면 API 비용 + 지연 + 무한루프 위험

**확정된 구조**:

Agent 3 역할 분리:
- 기획 결정만 담당 (zone_label만 출력 — placement_slot 출력 금지)
- 위치 탐색은 코드가 전담

Agent 3 output 스키마 (zone_label 통일):
- 소형/대형 구분 없이 Agent 3은 항상 zone_label만 뱉음
- 소형 공간은 zone당 placement_slot 1개라 결과 동일
- Union 타입 채택 안 함 — target_type 오태깅 버그 위험

공간 크기 기준 분기 (`space_data["floor"]["usable_area_sqm"]`):
- 코드가 zone 안 placement_slot 전체 순회 (소형/대형 공통)
- 기준선 수치는 실제 도면 테스트 후 결정

물리적 한계 vs cascade failure 구분:
```
placement_slot 전체 순회 전부 실패
→ 단독 배치 테스트 (빈 도면에 해당 오브젝트만)
  → 단독 실패 = 물리적 한계 → Graceful Degradation
  → 단독 성공 = cascade failure → Global Reset + Agent 3 재호출
```

placed_because 처리:
- Agent 3 기획 의도 보존
- 코드가 위치 조정한 경우: "1차 지정 위치(X) 공간 부족으로 인접 구역(Y) 자동 조정" 한 줄 추가

---

---

## Issue 8. 벽면 추상화 — LineString + 수선의 발

**문제**: wall_surface_y 단일 좌표는 수직/수평 벽 전제. 사선/곡선 벽에서 calculate_position이 틀린 좌표 산출.

**확정**:
- 벽을 LineString 객체로 저장 (시작점 + 끝점)
- calculate_position의 wall_facing 연산 시 Shapely `LineString.project()` + `interpolate()`로 수선의 발 계산
- 오브젝트 중심점 → wall_linestring 수선 교점 → depth/2 만큼 법선 벡터 방향으로 평행 이동

```python
# Agent 2 후반부 저장
space_data["north_wall_mid"]["wall_linestring"] = LineString([(0,4000),(6000,4000)])

# calculate_position wall_facing 연산
foot = wall_linestring.interpolate(wall_linestring.project(Point(ref_x, ref_y)))
# foot에서 법선 방향으로 depth/2 이동 → 오브젝트 중심점
```

---

## Issue 9. step_mm 공식 확정

**문제**: bbox_w만 기준으로 삼으면 얇고 긴 오브젝트(w=100, d=2000)에서 step이 극단적으로 작아짐.

**확정**:
```
step_mm = sqrt(w² + d²) × ratio
```
- 오브젝트 실제 점유 크기(대각선)에 비례하는 일관된 보폭
- ratio 초기값 미결 — 실제 도면 테스트 후 결정

---

## Issue 10. zone 경계 — Shapely Polygon + contains 선행 검사

**문제**: zone이 점의 집합이면 코드 탐색 중 인접 zone으로 이탈 가능.

**확정**:
- Agent 2 후반부에서 zone을 Shapely Polygon으로 저장
- Voronoi Diagram 채택 안 함 — 벽/Dead Zone으로 자연 구획되므로 정적 분할로 충분

```python
space_data["mid_zone"]["boundary"] = Polygon([(x1,y1),(x2,y2),...])
```

- attempt_placement 탐색 시 충돌 검사 이전에 contains 선행 체크
```python
if not zone_polygon.contains(object_bbox):
    continue  # zone 이탈 → 즉시 다음 좌표
```

---

---

## Issue 11. NetworkX 과부하 — buffer 근사 검증 도입

**문제**: step_mm 이동마다 NetworkX 전체 재연산 → 서버 다운

**확정**:
- 미세 조정 루프 안: Shapely buffer(450) 근사 검증만 사용
- 오브젝트 확정 시: NetworkX 최종 1회 교차 검증

**buffer 근사 원리**:
- 장애물 + 벽에 buffer(450) 적용 → 팽창된 장애물이 서로 맞닿으면 900mm 통로 막힘 판정
- 보수적 근사 → false positive 가능 (실제 통과 가능한데 막혔다고 판정)
- false positive는 attempt_placement 루프 몇 번 더 도는 비용만 발생
- false negative(통로 막혔는데 통과 판정)보다 압도적으로 안전한 trade-off

**필수 로직 A — 가상 입구 선분 (Virtual Entrance Line)**:
- 입구는 점이 아니라 선분 (예: 2000mm 개구부)
- 단일 점 451mm 이동 방식 폐기
- Shapely `offset_curve`로 입구 선분 전체를 벽 법선 방향으로 (450 + 10)mm 평행 이동
- 가상 입구 선분이 팽창된 장애물에 1mm라도 노출되면 출발 가능(True) 판정

**필수 로직 B — 캐시 생명주기 (Cache Lifecycle)**:
- 확정된 기물 + 벽면 buffer 병합본 1회 캐싱 → 루프 안에서 임시 오브젝트만 추가 체크
- Global Reset 발생 시 (`placed_objects.clear()` 즉시) `static_buffered_obstacles` 캐시 동시 파기
- 재진입 시 고정 벽체 데이터만으로 캐시 재계산

---

