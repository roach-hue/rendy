# Task Plan — 현재 상태

> 세션 시작 시 "지금 어디까지 왔나" 확인용. 상세 설계 결정 → `architecture_decisions.md`

---

## 현재 Phase: 아키텍처 설계 완료 → 구현 미시작

---

## 완료 (설계/기획)

- [x] Agent I/O 흐름 구조 va (`old/_Agent_IO_._va.md`)
- [x] 전체 개발 로드맵 va (`old/_._va (1).md`)
- [x] architecture_decisions.md (Issue 1~22 확정)
- [x] for_gemini.md (변경 요약 + 기각 목록)
- [x] 주요 설계 결정 확정:
  - Agent 1: Regex 전처리 hybrid (텍스트 PDF)
  - Agent 3 output: zone_label 통일 (placement_slot 출력 금지)
  - cascade failure: Global Reset + Choke Point intersects 원인 추출
  - 물리적 한계: Graceful Degradation (단독 배치 테스트 분기)
  - Deterministic Fallback 3단계 (Issue 15)
  - NetworkX: 미세 조정 루프 제외, 확정 시 1회만
  - buffer 이원화: main_artery buffer(600) + 일반 통로 buffer(450) (Issue 19)
  - step_mm: sqrt(w²+d²) × ratio 동적 계산
  - zone: walk_mm 기반 (Shapely Polygon 경계 방식 폐기 — Issue 16)
  - Hybrid Sampling: wall_facing 1D / inward·center 2D 격자 (Issue 17)
  - 격자점 0개 fallback: 중앙 + 양 끝 3개
  - 관계 제약 검증: Shapely.distance < clearspace_mm (Issue 14, zone_label 비교 기각)
  - calculate_position: LineString + 수선의 발 (Issue 8)
  - outward: 더미 처리
  - 충돌 판정: intersection().area > 0, Dead Zone만 intersects() (Issue 20)
  - inward/center 회전: Width Perpendicular (Issue 21)
  - 도면 타입: 평면도 + 단면도, ParsedDrawings 스키마 (Issue 22)
  - ceiling_height_mm: 단면도 추출, 없으면 기본값 3000mm
  - placement_slot 명칭 확정 (구 reference_point)
  - placed_because / adjustment_log 필드 분리

---

## 테스트 후 조정 (구현 중 실측값으로 확정)

- [ ] step_mm ratio 수치 — 실제 도면 테스트 후 조정
- [ ] 소형/대형 공간 기준선 (usable_area_sqm) — 실제 도면 테스트 후 조정
- [ ] walk_mm zone 임계값 수치 — 실제 도면 테스트 후 조정
- [x] inward/center 오프셋 규칙 — Issue 17 Hybrid Sampling으로 해소 (격자점 = 오브젝트 중심)
- [x] inward/center 회전 규칙 — Issue 21 확정 (Width Perpendicular)

---

## P0 구현 단계 (9단계 — 세션 1개 = 1단계)

### 의존성 그래프

```
P0-1 (스키마)
 ├→ P0-2 (도면 감지) → P0-3 (공간 연산)
 ├→ P0-4 (브랜드 추출) ← P0-2/3과 병렬 가능
 └→ P0-5a (좌표 계산) → P0-5b (순회 루프) → P0-5c (실패 처리)
                                              → P0-6 (검증) → P0-7 (출력)
```

### 단계별 상세

- [ ] **P0-1**: space_data 스키마 + Pydantic 모델 정의
  - space_data dict 구조 코드화
  - Placement, BrandField 등 Pydantic 모델
  - DEFAULTS dict 정의
  - 규모: 소

- [ ] **P0-2**: Agent 2 전반부 — 도면 감지 (OpenCV + Vision)
  - FloorPlanParser 추상 클래스 + 어댑터 (DXF/PDF/Image)
  - OpenCV polygon 추출
  - OCR 스케일 계산
  - Claude Vision 6가지 동시 감지
  - ParsedDrawings 스키마 출력
  - 의존: P0-1 | 규모: 대

- [ ] **P0-3**: Agent 2 후반부 — 공간 연산 (Shapely + NetworkX)
  - 픽셀→mm 변환, floor_polygon 차감, 내부 벽 추가
  - Dead Zone 생성
  - placement_slot + wall_linestring + wall_normal
  - NetworkX 격자 그래프 + walk_mm + zone_label 부여
  - Main Artery 캐싱
  - Agent 3용 자연어 요약
  - 의존: P0-1, P0-2 | 규모: 대

- [ ] **P0-4**: Agent 1 — 브랜드 수치 추출 (Regex + LLM)
  - PDF 텍스트 추출 + Regex 수치 기계 추출
  - LLM 라벨링 (5개 필드)
  - 이미지 PDF → Vision fallback
  - Pydantic 검증 + Circuit Breaker
  - 의존: P0-1 | 규모: 중 | **P0-2/3과 병렬 가능**

- [ ] **P0-5a**: calculate_position — direction별 좌표 계산
  - wall_facing: LineString + 수선의 발
  - inward/center: 격자점 = 중심, Width Perpendicular 회전
  - 모서리 4개 → Shapely polygon 생성
  - 오브젝트 선별 모듈 (Supabase 대조)
  - 의존: P0-1, P0-3 | 규모: 중

- [ ] **P0-5b**: 코드 순회 루프 — 배치 엔진
  - Hybrid Sampling (wall_facing 1D / inward·center 2D)
  - step_mm 동적 계산
  - Shapely 충돌 체크 (intersection.area > 0, Dead Zone intersects)
  - buffer 이원화 (Main Artery 600 + 일반 450)
  - NetworkX 최종 1회 확정
  - 관계 제약 검증 (distance < clearspace_mm)
  - 의존: P0-5a | 규모: 대

- [ ] **P0-5c**: 실패 처리 — Global Reset + Deterministic Fallback
  - 단독 배치 테스트 (cascade vs 물리적 한계 분기)
  - Choke Point intersects 원인 추출 + f-string 피드백
  - Agent 3 재호출 (최대 2회)
  - Deterministic Fallback (zone 무시 강제 배치)
  - Graceful Degradation (드랍)
  - 의존: P0-5b | 규모: 대

- [ ] **P0-6**: 검증 모듈 — 소방/시공 최종 검증
  - 소방 주통로 900mm, 비상 대피로 1200mm
  - Dead Zone 침범, 벽체 이격 300mm
  - blocking vs warning 분류
  - verification_result 출력
  - 의존: P0-5c | 규모: 중

- [ ] **P0-7**: 출력 — .glb 생성 + Agent 5 리포트
  - layout_objects + DB 높이값 → Three.js Whitebox → .glb
  - f-string 템플릿 리포트 기계 조립
  - source별 표기, placed_because, adjustment_log, fallback 항목, disclaimer
  - 의존: P0-5c, P0-6 | 규모: 중
