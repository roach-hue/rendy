# Progress Log

> 세션별 완료 내용, 에러, 다음 시작점 기록.

---

## 2026-04-01

### 완료 (설계/기획 세션)

- Agent I/O va 기반으로 아키텍처 전면 재설계
- architecture_decisions.md 생성 (Issue 1~14)
- Gemini와 설계 검토 — 주요 변경 반영
- for_gemini.md 생성 (변경 요약 전달용)
- architecture_review.md 기반 4개 오류 수정:
  - Issue 6/8 공존 → Issue 6 폐기 표시
  - inward/outward/center 중심점 오류 수정
  - 격자점 0개 fallback (중앙 + 양 끝 3개)
  - 관계 제약 검증 (Issue 14 — zone_label 비교 기각 → Shapely.distance + clearspace_mm 확정)
- outward direction 더미 처리
- task_plan.md + progress.md 생성

### 주요 결정 (오늘)

- Agent 3 output: zone_label 통일
- cascade failure: Global Reset + Choke Point intersects
- NetworkX: 확정 시 1회만 (미세 조정 루프 제외)
- buffer(450) 근사 + 가상 입구 선분 offset
- step_mm: sqrt(w²+d²) × ratio
- 관계 제약: Shapely.distance < clearspace_mm로 검증 (Issue 14 — zone_label 비교 기각)

### 에러/주의

- 없음

### 다음 세션 시작 지점

- 미결 4개 확인 후 P0 구현 시작 (명시적 지시 필요)
- .claude/skills/ + agents/ 는 구현 시작 시점에 생성

---

## 2026-04-02

### 완료 (하네스 동기화 세션)

- 클로드 코드: 전체 md 파일 하네스 엔지니어링 형태 동기화
  - archive/2026-04-02/ 백업 (architecture_decisions, architecture_spec, agents 4개, skills 7개)
  - brand_extraction.md Issue 14 기각 방식 수정
  - agent-2-floorplan.md Issue 16-22 반영
  - agent-5-report.md Issue 15 fallback source 반영
  - claude.md ParsedDrawings + zone_label 용어 수정
  - architecture_spec.md inward/center Issue 17/21 반영 (1/3 완료 후 세션 한도)
- Gemini(Antigravity): 클로드 코드 끊긴 작업 이어서 완료
  - architecture_spec.md ceiling_height_mm 추가 (Issue 22)
  - architecture_spec.md 테스트 후 조정 테이블 해소 항목 표기
  - progress.md Issue 14 기록 업데이트
  - claude.md Agent 3 재호출 피드백 규칙 업데이트 (Issue 12)

### 에러/주의

- 클로드 코드 세션 한도 (2pm KST 리셋)

### 다음 세션 시작 지점

- architecture_decisions_part1/2a/2b.md 정리 여부 결정 (마스터와 중복)
- P0 구현 시작 (명시적 지시 필요)

---

## 2026-04-02 (구현 세션 2~3)

### 완료

- P0-5a: calculate_position + object_selection (Supabase 연동)
- P0-5b: placement_engine (충돌·통로·관계 제약)
- P0-5c: failure_handler (cascade + deterministic fallback)
- P0-6: verification (소방/시공 최종 검증)
- P0-7: report_generator + glb_exporter
- Agent 3: LLM 배치 기획 (Claude Sonnet)
- FE-4: Three.js 3D 뷰어 (R3F 8 + drei 9 + three 0.160)
- 전체 파이프라인 통합 API (/api/placement)
- Supabase furniture_standards 테이블 + 연동
- 캐시 저장/로드 API (/api/cache-save, /api/cache-load)
- 오브젝트 CRUD API (/api/objects)
- 포트 확정: 8001 백엔드, 5174 프론트

### 미해결 (이전 세션) → 수정 완료 (2026-04-02)

1. ~~`/api/placement` 500 에러~~ → **수정 완료**
   - `_strip_shapely`에 numpy 타입(`np.integer`, `np.floating`, `np.ndarray`) + tuple 처리 추가
   - `_serialize_space_data` / `_serialize_space_data_deep`을 `_strip_shapely` 재사용으로 통합
   - 서버 재시작 후 검증 필요

2. ~~`/api/detect` 422 에러~~ → **수정 완료**
   - `_parse_json_lenient()` 함수 추가: 작은따옴표→큰따옴표, trailing comma 제거, // 주석 제거
   - 원본 파싱 실패 시 repair 후 재시도, 그래도 실패 시 명확한 에러 메시지

3. ~~3D 뷰어 검정 바닥/오브젝트~~ → **1차 수정 실패, 2차 수정 완료**
   - 1차: `ColorVisuals()` → `face_colors` 명시 → **여전히 검정** (trimesh가 GLB export 시 vertex colors를 검정으로 bake)
   - 2차 근본 원인: trimesh `face_colors`(ColorVisuals)가 GLB로 export 시 검정 vertex color로 bake → Three.js에서 material color를 덮어씀
   - 2차 백엔드 수정: `face_colors` → `SimpleMaterial` + `TextureVisuals`로 교체 (PBR material로 GLB에 색상 보존)
   - 2차 프론트 수정: `geometry.deleteAttribute("color")` 추가 (잔여 vertex colors 제거, material color 우선)

4. ~~바닥 메시 사각형 문제~~ → **수정 완료**
   - `box()` → `trimesh.creation.extrude_polygon(shapely_polygon)` 교체
   - XY→XZ 좌표계 변환 (X축 -90° 회전)
   - 실패 시 bbox box() fallback 유지

### 설계 결정 (이번 세션)

- rotation_deg 자유 회전 + 15° 안전장치 + direction fallback
- OpenCV 위치 + Vision 치수 결합 (polygon 감지)
- detected_width_mm/height_mm 자동 채움
- session_cache 테이블 (Supabase)

### 에러/주의

- R3F 9 + Three.js 0.169 호환 불가 → R3F 8 + Three.js 0.160으로 다운그레이드
- bash에서 PowerShell 플래그 경로 해석 문제 지속
- 포트 좀비 프로세스 반복 발생

---

## 2026-04-02 (기술 부채 해소 세션)

### 완료

**3D 뷰어 색상 (3차 수정 — 최종 해결)**
- 근본 원인: trimesh `ColorVisuals`/`SimpleMaterial`이 GLB export 시 vertex colors(0,0,0)로 bake → Three.js material 덮어씀
- 해결: 백엔드 `PBRMaterial` + `TextureVisuals` (glTF 표준 pbrMetallicRoughness), 프론트 `deleteAttribute("color")` + `MeshBasicMaterial`
- `MeshStandardMaterial`은 조명 문제로 검정 → `MeshBasicMaterial`로 확정 (whitebox 프리뷰 용도)
- `mapbox-earcut` conda base 설치 → `extrude_polygon` 정상 작동
- 바닥 mirror 반전: extrude 후 centroid 원점 이동 → 회전 → 벽 좌표 복원

**설계 vs 구현 차이 분석 (Gemini 교차 검증)**
- 핵심 미구현 항목 발견: step_mm 하드코딩, 격자점 탐색 없음, Zone 경계 불일치, NetworkX 통로 미연결 등
- Graceful Degradation만 설계대로 구현, 나머지 대부분 단순화/placeholder

**P0: 겹침 즉각 차단**
- `_deterministic_fallback`: 배치 즉시 `all_existing`에 추가 → 다음 기물 충돌 인식
- `_is_join_pair`: `join_with`/`object_type` 둘 다 존재할 때만 충돌 스킵
- `_classify_failures`: `entrance_zone` 하드코딩 제거 → 원본 placement zone/direction 사용
- Global Reset 루프 폐기 (Agent 3 재호출 없이 무의미) → 즉시 deterministic fallback

**P1: 탐색 지능 복구**
- step_mm: 2000mm 하드코딩 → `sqrt(max_w² + max_w²) × 0.7` 동적 계산 (500~2000 클램프)
- 격자점 탐색: inward/center에서 법선 방향 300mm×8단계 후보 생성 + floor.contains() 필터
- Zone 경계: 하드코딩 → 공간 크기 비례 동적 계산 (bbox 최대변 × 0.33/0.66 분할)

**P2: 고도화 검증 로직 (완료)**
- P2-3: Inner Walls → Dead Zone 변환 (INNER_WALL_BUFFER_MM=150, 상수 분리)
- P2-2: Zone 2차 검증 + 양방향 확장 (_expand_zone: deep→mid, mid→entrance/deep, entrance→mid)
- P2-4: Virtual Entrance (entrance_width_mm 스키마 추가, DXF 파서 추출, agent2 buffer 생성, C4.5 체크)
- P2-1: NetworkX 통로 연결성 (build_corridor_graph export, 매 배치마다 incremental 검증)
- 테스트 결과: 겹침 0건, 배치 75% (12/16), 드랍 25% (4/16)

**파이프라인 최종 보수**
- Agent 3 Hard Limit: MAX_AVAILABLE_SLOTS 프롬프트 주입 → slot 수 초과 기획 방지
- SceneViewer: MeshStandardMaterial 조명 문제 미해결 → MeshBasicMaterial 확정 (whitebox 프리뷰 용도)
- 바닥 mirror 반전 최종 해결: X축 -90° 회전 → Y↔Z 축 swap 행렬로 교체 + fix_normals()

### 에러/주의

- pip install이 system Python에 설치되는 문제 반복 — conda base 확인 필수

---

## 2026-04-02 (구현 세션 1)

### 완료

- P0-1: 스키마 + 기반 코드
  - `backend/app/schemas/` — BrandField, Placement, ParsedDrawings(ParsedFloorPlan/ParsedSection), SpaceData TypedDict
  - `backend/app/core/defaults.py` — DEFAULTS dict + merge_with_defaults()
  - `backend/requirements.txt`
- 앱 기반: `backend/main.py` + `backend/app/api/routes.py` (POST /api/detect)
- P0-2: 도면 감지 파서
  - `FloorPlanParser` 추상 클래스 (`app/parsers/base.py`)
  - `factory.py` — 확장자 기반 파서 선택 (DXF/PDF/PNG·JPG 분기)
  - `ImageParser` — OpenCV polygon 추출 + Claude Vision 6-item 1회 호출
  - `PDFParser` — PyMuPDF 래스터화 → ImageParser 위임
  - `DXFParser` — ezdxf 직접 파싱, LWPOLYLINE 외벽/내벽/입구/단면도 ceiling_height_mm
  - `test_p02.py` — 단일 파일 테스트 스크립트
- 기타 스킬/규칙 업데이트
  - `object_selection.md` 명세 정밀화 (Supabase 쿼리 구조, Agent 3 핸드오프 규칙)
  - `brand_extraction.md` Agent 1 담당 범위 명시
  - `floorplan_detection.md` ParsedFloorPlan 클래스 추가
  - `claude.md` Agent 간 I/O 명칭 통일 규칙 + 확정 명칭 목록 추가
  - `relationships` → `object_pair_rules` 전체 파일 교체
  - `ParsedFloor` → `ParsedFloorPlan`, `floor` → `floor_plan` 필드명 통일
  - `architecture_decisions.md` Issue 23 dragend 패턴 등록
- 프론트엔드 기반
  - `frontend/src/hooks/useDragControls.ts` — dragend 패턴 (Issue 23)
  - `frontend/src/api/layout.ts` — PATCH /layout/{id}/object/{type}
  - `frontend/src/components/viewer/SceneViewer.tsx`

### 에러/주의

- `_estimate_scale()` — OCR 미구현. 현재 scale_mm_per_px=10.0 하드코딩. 실측 도면 테스트 필요.
- DXF `inaccessible_rooms` 미구현 — 레이어 기반 폐쇄 공간 감지 로직 추가 필요.
- DXF 설비(스프링클러·소화전·분전반) 심볼 블록명 미구현 — 실제 DXF 샘플 확인 후 블록명 매핑 필요.
- PyMuPDF (fitz) 미설치 — PDF 테스트 시 `pip install pymupdf` 필요.

### 다음 세션 시작 지점

- 실제 도면 파일로 `python test_p02.py <파일>` 실행 → polygon/scale 결과 검증
- OCR scale 계산 구현 (`_estimate_scale`)
- P0-3: Agent 2 후반부 — Shapely Dead Zone + placement_slot + NetworkX
