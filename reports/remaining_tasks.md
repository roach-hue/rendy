# Rendy 작업 이력 + 남은 작업

---

## 2026-04-06 완료 항목 (이전 커밋 421f0ee 포함)

### DXF 파서 대규모 보강
- ARC/CIRCLE tessellation (CHORD_TOLERANCE=50mm)
- LWPOLYLINE bulge 원호 변환
- TEXT/MTEXT 앵커링 (ENTRANCE, STAFF ONLY → 좌표 추출)
- 설비 심볼 추출 (INSERT 블록 패턴 매칭)
- 3대 안전장치: 좌표 정규화, 스냅 톨러런스(5mm), 폴백 사각형
- ezdxf.readfile 임시파일 경유 (ANSI_1252 인코딩 대응)

### DXF 프리뷰 렌더링
- matplotlib 기반 DXF → PNG 래스터화
- 색상 반전 (흰색→검정), viewport 동기화

### 프론트엔드 좌표 동기화
- useMarkingCanvas.ts: DXF mm↔캔버스 변환, 복수 입구 지원
- ConfirmPage: Voronoi grid fill + floor polygon clip
- 확대/축소 버튼 (+/-/초기화)

### Y-up 좌표계 통일
- calculate_position.py: north=(0,1), south=(0,-1)
- slot_generator.py: ny>0→"north"

### 입구 좌표 스냅 + 복수 입구
- agent2_back.py: _snap_point_to_polygon(), _snap_entrances()
- walk_mm_calculator.py: dict/DetectedEntrance/tuple 3형태 수용

### Choke Point 피드백 활성화
- placement_engine.py: 900mm 병목 검증
- failure_classifier.py: 동선 병목/슬롯 부족 분리 표시

### category 유실 차단
- fallback/engine에 height_mm/category 추가, 프론트 isCylinder 방어

### IQI 지능형 물량 산출
- MAX_DENSITY_RATIO=0.25, priority_score 정렬, 프롬프트 주입

### Generative Asset Provisioning
- Agent 3 제안 기물 중 DB에 없는 것 → furniture_standards INSERT

### 캐시 바이패스
- drawings hash 기반 placement 캐시, 동일 도면 LLM 0회

### InstancedMesh (C-4/C-5)
- geometry_id 그룹화, GLB fallback 모드

### MultiPolygon 방어
- agent2_back.py: difference() 결과 최대 조각 선택

### Agent 2 모듈 분리 (agent2_back.py 820줄 → 6개 파일)
- agent2_summary.py, corridor_graph.py, dead_zone_generator.py
- slot_generator.py, walk_mm_calculator.py

### 파이프라인 모듈 분리 (routes.py 348줄 → 5개 파일)
- pipeline.py, cache_service.py, file_converter.py, object_crud.py, serializer.py

---

## 2026-04-06~07 세션 완료 항목 (본 대화)

### 문제 1: 3D 동선 리본 바닥 묻힘 — 해결
- **증상**: 핑크색 Ribbon Mesh가 바닥에 묻혀 안 보임 (ROAD_Y=2,8,15 전부 묻힘, 50에서만 보임)
- **근본 원인**: 카메라 near=1 / far=100000 (비율 100,000:1) → 24bit 깊이 버퍼 해상도가 카메라 거리 15000mm에서 ~13mm. 바닥(Y=5)과 리본(Y=8)의 3mm 차이를 GPU가 구분 불가
- **수정**: SceneViewer.tsx에 `logarithmicDepthBuffer: true` + `near: 10` 적용. ROAD_Y=6으로 정상 동작
- **파일**: `frontend/src/components/viewer/SceneViewer.tsx`

### 문제 2: Main Artery가 무의미한 대각선 — 해결
- **증상**: 입구(30000,0) → 우하단(99500,99500) 대각선 1줄. 매장 절반 미커버
- **근본 원인**: Dijkstra 최단경로가 균일 그리드에서 대각선+직선 조합의 계단형 경로 생성
- **수정**: `_compute_main_artery()` → `_build_main_spine()` 전면 교체. VMD 정석 직각 주동선(Main Spine) 생성. 입구 → 바닥 중심 → 최원 벽면 중앙까지 ㄱ자 직각 경로
- **결과**: 4 경유점, 239 그리드 노드, 입구(30000,500) → 꺾임(30000,50000) → (50000,50000) → 종점(50000,99500)
- **파일**: `backend/app/agents/walk_mm_calculator.py`

### 문제 3: Agent 3이 주동선을 모름 — 해결
- **증상**: Agent 3 프롬프트에 동선 정보 없음. 기물 배치가 동선과 무관
- **수정 (3단계)**:
  1. 슬롯별 `spine_rank` 메타데이터 부여 (adjacent/nearby/far) — `agent2_back.py` `_assign_spine_proximity()`
  2. Agent 3 시스템 프롬프트에 `[P4. 주동선 종속 배치]` 규칙 추가 — Hero는 adjacent에만, 보조는 far 허용
  3. Agent 3 유저 프롬프트에 `## 주동선(Main Spine) 구조` 섹션 추가 — 경유점 + 구간 방향을 자연어로 서술 (mm 수치 미전달)
- **파일**: `backend/app/agents/agent2_back.py`, `backend/app/agents/agent3_placement.py`, `backend/app/agents/agent2_summary.py`

### 문제 4: placement_engine 슬롯 정렬이 Spine 무시 — 해결 (2회 수정)
- **1차 수정**: walk_mm 오름차순 → spine_rank(adjacent→nearby→far) 1차 + walk_mm 2차
- **문제 발생**: 모든 기물이 좌측 Spine 인접에 몰림. 우측 벽면 완전 미활용
- **2차 수정**: direction 기반 분기 정렬. `wall_facing`(선반/배너) → `_SPINE_FAR_FIRST` (반대편 벽면 우선). `inward/center`(핵심 기물) → `_SPINE_NEAR_FIRST` (주동선 인접 우선)
- **결과**: shelf_wall이 X=60000(우측)까지 분산, hero 기물은 Spine adjacent 유지
- **파일**: `backend/app/modules/placement_engine.py`

### 문제 5: 부동선(Sub-path) 미생성/빈 공간 경유 — 해결 (3회 수정)
- **1차 구현**: 바닥 꼭짓점 중 Spine에서 5m+ 떨어진 것 경유 → 좌하단 편중, 우측 미커버
- **2차 수정**: 기물 기반 경유점으로 교체 → 기물 전부 adjacent면 부동선 미생성
- **3차 수정 (최종)**: 기물 경유점 우선 + Spine 반대편 외곽 의무 경유 fallback. 기물 없어도 100% 생성 보장. Spine 좌측이면 우측 외곽 3점 의무 경유, 반대면 좌측
- **파일**: `backend/app/api/pipeline.py` `_build_sub_path()`

### 문제 6: Agent 3 rate limit (429) — 해결
- **증상**: 2500개 슬롯 전체를 Agent 3 프롬프트에 나열 → 토큰 과다 → 30,000 input tokens/min 초과
- **수정**: `agent2_summary.py` 대규모 요약 모드 추가. 100+ 슬롯 시 통계 요약(zone×spine 분포) + 대표 슬롯 샘플(조합별 3개)로 축소. 2500줄 → 50줄, ~2950자
- **파일**: `backend/app/agents/agent2_summary.py`

### 문제 7: 입구가 3D에 안 보임 — 해결 (2회 수정)
- **1차 구현**: 바닥 초록색 삼각형(ConeGeometry) + 수직 기둥(CylinderGeometry)
- **문제 발생**: 기물처럼 보여 시각적 혼란
- **2차 수정**: 3D 입체물 전부 삭제 → 바닥 밀착 2D 데칼(RingGeometry + 십자 LineSegments). 두께 0, 높이 0
- **백엔드**: `pipeline.py` `_build_floor_viz()`에 `entrances` 좌표 추가
- **파일**: `frontend/src/components/viewer/useGLBScene.ts`, `backend/app/api/pipeline.py`, `frontend/src/api/placement.ts`

### 기능 추가: 오브젝트 라벨 ON/OFF
- 각 기물 위에 영어 라벨 표시 (object_type → PascalCase: `Character Hellokitty`, `Display Table`)
- 툴바에 Labels ON/OFF 토글 버튼
- drei `<Html>` 컴포넌트 사용, pointerEvents: none
- **파일**: `frontend/src/components/viewer/SceneViewer.tsx`

### 확인 완료: 소화전/분전반 배치 회피
- 스프링클러(300mm), 소화전(500mm), 분전반(600mm) → dead_zone으로 변환 → placement_engine static_cache에 병합 → 배치 시 intersects 체크로 회피
- 코드 정상 동작 확인. 범위가 작아 시각적으로 잘 안 보일 뿐

### 버그 수정: `mandatory` NameError
- **증상**: `_build_sub_path()` 3차 수정 시 변수명 `mandatory` → `fallback`으로 변경했으나 로그 출력문에 구명칭 잔존
- **수정**: 로그에서 `mandatory` 참조 제거

---

## 남은 작업

### 코어 파이프라인 완성

| # | 항목 | 상태 | 비고 |
|---|------|------|------|
| 1 | 복수 입구 walk_mm 순회 | **완료** | min(전체 입구) + zone_label은 MAIN 기준 |
| 2 | MeshStandardMaterial PBR 조명 | 대기 | MeshBasicMaterial 우회 중, 3D 납작하게 보임 |

### 필수 — 배포 전 구현

| # | 항목 | 상태 | 비고 |
|---|------|------|------|
| 3 | **세션 영속화 (배치 결과 저장)** | **미구현** | 현재 로컬 캐시 파일만 의존. Supabase sessions 테이블에 도면ID+배치결과 저장 → 재방문 시 복원 → 수정 시 delta 적용 필요. 없으면 캐시 삭제/서버 재시작마다 배치 소멸 |
| 4 | E2E deterministic 테스트 | 대기 | Agent 3 mock 필요 |
| 5 | 배포 설정 | 대기 | — |

### 실 데이터 의존 (블로킹)

| # | 항목 | 상태 | 비고 |
|---|------|------|------|
| 6 | DXF 설비 심볼 매핑 | 블로킹 | 실제 DXF 샘플 필요 |
| 7 | step_mm / zone 임계값 실측 조정 | 블로킹 | 실제 도면 다수 필요 |

### 기능 확장

| # | 항목 | 상태 | 비고 |
|---|------|------|------|
| 8 | Agent 4 (동선 최적화 + 스타일) | 미착수 | 레퍼런스 참고 → zone 내 슬롯 재배치로 부동선 꼬임 해소. 입력: 부동선 교차 횟수, 경유 순서 역전 지표. zone 변경 금지, 슬롯 교체만 |
| 9 | DXF 이중선 벽 자동 판별 | 미착수 | 실무 DXF는 벽 두께 이중선(150~200mm). 현재 polygon 2개 생성 시 혼동. 면적 큰 쪽 = 외벽, 작은 쪽 = 내벽으로 자동 판별 필요 |
| 10 | 도면 고정 오브젝트 감지 | 미착수 | 도면에 이미 그려진 기물(SHELF, COUNTER 등)을 TEXT+위치로 감지 → 고정 오브젝트로 사전 등록 → Agent 3 배치 대상에서 제외, placement_engine에서 이동 금지 |

---

## 2026-04-07 오후 작업 계획 (12:00~)

| 순서 | 항목 | 예상 |
|------|------|------|
| 1 | PBR 조명 (MeshStandardMaterial) | 3D 결과물 품질 개선 |
| 2 | 세션 영속화 설계 + 구현 | Supabase sessions 테이블, 배치 결과 저장/복원 |
| 3 | Agent 4 설계 + 구현 | 부동선 꼬임 지표 입력 → zone 내 슬롯 재배치 → 부동선 재생성 |
| 4 | E2E deterministic 테스트 | Agent 3 mock으로 결정론적 테스트 |
