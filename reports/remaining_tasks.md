# 남은 작업 목록

## 기능 완성 (13/15 완료)

| # | 항목 | 상태 |
|---|------|------|
| 1 | 마킹 UI | **완료** |
| 2 | ConfirmPage zone 컬러맵 | **완료** |
| 3 | 3D 뷰어 드래그/회전 | **완료** |
| 4 | 스케일 앵커 UI | **완료** |
| 5 | PDF 벡터 파서 재작성 | **완료** |
| 6 | Rotation 제약 + Wall Snap | **완료** |
| 7 | VerificationResult 스키마 | **완료** |
| 8 | SummaryReport 스키마 | **완료** |
| 9 | inaccessible Dead Zone 반영 | **완료** |
| 10 | fallback 검증 누락 수정 | **완료** |
| 11 | Semantic Tag 파이프라인 | **완료** |
| 12 | NetworkX 우회 보행 경로 | **완료** |
| 13 | E2E 테스트 | **PASS** |
| 14 | DXF 설비 심볼 매핑 | 대기 (샘플 필요) → Phase 4 |
| 15 | 에러 핸들링 통합 | 대기 → Phase 1 |
| 16 | Vision 프롬프트 튜닝 | 대기 | polygon/inaccessible/스케일 감지 정확도 개선 (VISION_PROMPT) |
| 17 | PDF 미리보기 이미지 | **완료** | preview_image_base64 응답 추가 |

---

## 고도화 실행 순서

### Phase 1: 백엔드 엔진 최적화 및 안정성 확보 (리스크 0%)

I/O 스키마 변경 없이 내부 연산 효율 + 방어력만 강화. 시스템을 흔들 위험 없음.

| 순서 | 항목 | 설명 |
|------|------|------|
| 1-1 | Static Cache 연산 최적화 | 정적 장애물(내벽·inaccessible·Dead Zone) 1회 Union → static_obstacle_cache. 루프에서 신규 bbox만 동적 합산 |
| 1-2 | 에러 핸들링 통합 | 시스템 전역 에러 캐치 방어선. 이후 고도화 버그 즉각 추적 기반 |
| 1-3 | overlap_margin_mm 실제 적용 | 충돌 체크에 이미 정의된 여백 파라미터 추가. 단순 연산 추가, 부작용 없음 |

### Phase 2: 공간 기하학 데이터 확장 (기존 로직 보존)

배치 엔진 코어 미변경. 파서/Agent 2가 생성하는 space_data 내용물만 풍부하게 확장.

| 순서 | 항목 | 설명 |
|------|------|------|
| 2-1 | inner_walls → wall_linestring 저장 | 내부 벽면 자료형을 외벽과 일치시키는 기초 데이터 정비 |
| 2-2 | 내부 slot 생성 (interior_slot) | 외벽 edge + 내부 격자 슬롯 추가. Agent 3 선택지 확장, 기존 벽면 배치 미훼손 |
| 2-3 | Choke Point 병목 탐지 | 450mm buffer 내 동선 교차·협소 구간 식별 → choke_points space_data 저장. 기존 Dead Zone 차단 로직과 동일 파이프라인 |

### Phase 3: 물리 연산 및 제어 흐름 고도화 (리스크 관리 구간)

배치 엔진의 기하학 판단 + 파이프라인 제어 흐름 변경. Phase 1~2 안정화 후 진행.

| 순서 | 항목 | 설명 |
|------|------|------|
| 3-1 | 벽 법선 벡터 실수화 + 4방위 제거 | Wall Snapping을 실제 사선 각도로 정밀화. 코어 각도 판정 변경 → 집중 테스트 필요 |
| 3-2 | Global Reset + Agent 3 재호출 복원 | 배치 실패 시 피드백 기반 재기획 루프. 엔진 정밀화(Phase 1~2) 후 무한 루프 방지 가능 |

### Phase 4: 예외 케이스 및 후반 작업 (가장 마지막)

코어 파이프라인과 거리가 멀거나 특정 상황에서만 발동하는 엣지 케이스 + 최종 마무리.

| 순서 | 항목 | 설명 |
|------|------|------|
| 4-1 | 곡선 벽 sagitta 근사 (Issue 18) | 비정형 도면 기하학 예외 |
| 4-2 | 복수 입구 지원 | walk_mm min(각 입구 거리) + Main Artery 재설계 |
| 4-3 | MeshStandardMaterial PBR 조명 | 프론트엔드 시각화 향상 (백엔드 무관) |
| 4-4 | DXF 설비 심볼 매핑 | 샘플 데이터 확보 후 진행 |
| 4-5 | step_mm ratio / zone 임계값 실측 조정 | 실제 현장 데이터 투입 후 파라미터 튜닝 |
| 4-6 | E2E deterministic 테스트 (Agent 3 mock) | 모든 기능 개발 완료 후 테스트 안정화 |
| 4-7 | SRP 리팩토링 4건 (routes/failure_handler/calculate_position/MarkingPage) | 기능 개발 완료 후 코드 분리 |
| 4-8 | 배포 설정 | 최종 마무리 |
