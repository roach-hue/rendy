# 파이프라인 1대1 비교 — Rendy vs Shin

> 작성일: 2026-04-05

---

## 1. 아키텍처 구조

| 비교 기준 | Rendy | Shin |
|----------|-------|------|
| 전체 단계 수 | 4단계 (업로드→감지/마킹→검토→배치) | 5단계 (업로드→감지/마킹→에어리얼확인→배치→3D편집) |
| 백엔드 | FastAPI (Python) | FastAPI (Python) |
| 프론트엔드 | React + Vite + TypeScript | Next.js + TypeScript |
| 3D 렌더링 | Three.js (R3F) | Three.js (R3F + drei) |
| AI 모델 | Claude Sonnet 4.5 | Claude Sonnet 4.6 |
| DB | Supabase | 미사용 (stateless) |
| 모듈 구성 | Agent 3 + 모듈 7 + 파서 4 + 스키마 4 | Agent 3 + 엔진 2 + 파서 1 + 레퍼런스 1 |
| API 수 | 8개 | 6개 |
| 처리 방식 | 동기 모놀리식 | Agent1+2a 병렬 → 순차 |

## 2. 입력 처리

| 비교 기준 | Rendy | Shin |
|----------|-------|------|
| 지원 파일 형식 | DXF / PDF / PNG·JPG | PDF only |
| 벡터 파일 파싱 | ezdxf 직접 + pdfplumber 벡터 추출 | pymupdf get_drawings() → polygonize |
| 래스터 처리 | OpenCV + Vision AI | OpenCV contour + Vision API |
| 파서 확장 구조 | 어댑터 패턴 (공통 출력 스키마) | 4중 방어 (polygonize→drawing별→Vision→수동) |
| 스케일 산출 | 치수선 매칭 자동 + 수동 앵커 UI | 치수선 최대값 자동 + 수동 입력 |
| 단면도 처리 | ceiling_height_mm 추출 | 미처리 |

### Rendy 미구현 요소
- polygonize 범용 파싱 미적용
- Agent1+2a 병렬 실행 미적용

## 3. 공간 분석

| 비교 기준 | Rendy | Shin |
|----------|-------|------|
| 좌표계 | mm | mm |
| 바닥 polygon | 자동 + 수동 드래그 편집 | 자동 (polygonize) + Vision fallback |
| 배치 불가 영역 | inaccessible + 설비 buffer + inner walls + Choke Point | Dead Zone + 입구 exclusion |
| Zone 분할 | walk_mm 동적 경계 (33%/66%) | walk_mm zone_label (entrance/near/mid/deep) |
| 통로 그래프 | NetworkX 격자 (500mm) | NetworkX 격자 (300mm) |
| 비상 통로 | Main Artery Dijkstra 우회 경로 | 경로 존재 확인 (단순화) |
| 입구 모델링 | 점 → 선분(폭) + buffer 460mm | 점/선분/polyline + 폭 비례 exclusion |

### Rendy 미구현 요소
- 4-zone 분할 (near zone 없음 — 3-zone만)
- 입구 폭 비례 exclusion (고정 460mm)

## 4. 브랜드 데이터

| 비교 기준 | Rendy | Shin |
|----------|-------|------|
| 입력 방식 | PDF 자동 추출 | PDF 자동 추출 |
| 추출 방법 | Regex + LLM hybrid | LLM only + Pydantic 검증 |
| 오브젝트 DB | Supabase furniture_standards | 미사용 (placement_rules 직접 추출) |
| 쌍 규정 | 분리/합체 + clearspace_mm | relationships 자연어 + min_clearspace_mm |
| 금지 소재 | prohibited_material 필터 | prohibited_material 필터 |

### Rendy 미구현 요소
- Stateless 서버 (NDA 대응) 미적용 — DB에 브랜드 데이터 저장

## 5. 배치 기획 (AI)

| 비교 기준 | Rendy | Shin |
|----------|-------|------|
| AI 역할 | zone + direction + alignment (좌표 금지) | ref_point + direction + priority + 수량 (좌표 금지) |
| 좌표 계산 | 코드 (Shapely/NetworkX) | 코드 (Shapely/NetworkX) |
| 회전 제약 | alignment Enum → wall_angle_deg 기반 | wall_angle_deg 자동 / freestanding 45도 단위 |
| 배치 수 제한 | MAX_AVAILABLE_SLOTS hard limit | 벽 수용량 상한 + LLM 자유 판단 |
| 재시도 | Circuit Breaker 3회 + Agent 3 재호출 | 코드 조정(±100mm) → 대안 ref → LLM 재호출 1회 |

### Rendy 미구현 요소
- LLM 수량 판단 (현재 slot hard limit으로 기계적 제한)
- 레퍼런스 이미지 참조 (Agent 4 미구현)

## 6. 배치 엔진

| 비교 기준 | Rendy | Shin |
|----------|-------|------|
| 충돌 감지 | Shapely intersection | Shapely intersection + buffer(gap_mm) |
| 통로 폭 검증 | 450mm / 1200mm 이원화 | 경로 존재만 (단순화) |
| 통로 연결성 | NetworkX has_path (매 배치마다) | NetworkX shortest_path (매 배치마다) |
| 벽면 정렬 | alignment Enum → wall_angle_deg snap | wall_angle_deg 자동 (wall_facing만) |
| 관계 제약 | Shapely.distance < clearspace_mm | placement_rules 하네스 |
| 증분 검증 | 오브젝트 단위 즉시 | 오브젝트 단위 즉시 |
| 격자점 탐색 | 법선 방향 다단계 후보 | 8방향 ±100mm × 10스텝 |

### Rendy 미구현 요소
- 곡선 벽 sagitta 근사 (Issue 18)
- 복수 입구 지원
- 가벽 오브젝트화 (Shin의 이동/크기조절/회전 가능 가벽)

## 7. 실패 처리

| 비교 기준 | Rendy | Shin |
|----------|-------|------|
| 실패 분류 | cascade vs physical limit | out_of_floor / dead_zone / shapely / corridor |
| fallback 전략 | deterministic (zone 무시, 전체 slot) | 코드 조정 → 대안 ref → LLM 재호출 (3단계) |
| AI 재호출 | 3회 (Choke Point 피드백 전달) | 1회 (실패 사유 + 점유 현황 전달) |
| Graceful Degradation | drop + 사유 명시 | violation warning + 가능한 것만 표시 |

### Rendy 미구현 요소
- 반려 피드백 반영 (사용자 반려 사유 → 재배치 전달)
- 도미노 검증 구간 (파이프라인 2곳 gate)

## 8. 검증

| 비교 기준 | Rendy | Shin |
|----------|-------|------|
| 검증 항목 수 | 5개 | 3개 |
| 소방 규정 | 통로 900mm + 비상로 1200mm | 입구 exclusion 1200mm + 경로 존재 |
| 시공 규정 | 벽체 이격 300mm | wall_clearance 300mm + object_gap 300mm |
| 결과 분류 | blocking / warning | blocking / warning |

## 9. 출력

| 비교 기준 | Rendy | Shin |
|----------|-------|------|
| 3D 모델 포맷 | GLB (trimesh PBRMaterial) | GLB (Three.js GLTFExporter) |
| 비정형 바닥 | extrude_polygon | ShapeGeometry |
| 텍스트 리포트 | f-string 템플릿 (source별 표기) | 미구현 |

### Rendy 미구현 요소
- MeshStandardMaterial PBR 조명 (MeshBasicMaterial 우회 중)

## 10. 사용자 개입

| 비교 기준 | Rendy | Shin |
|----------|-------|------|
| 도면 편집 | polygon/설비/inaccessible 드래그 편집 | 입구 polyline + 설비 클릭 마킹 |
| 스케일 교정 | 수동 앵커 (2점 + mm) | 수동 mm/px 입력 (1점) |
| 배치 후 조정 | 3D 드래그/회전 모드 토글 | 방향키 + 드래그 + 핸들 크기조절 + 45도 회전 + SizePanel |

### Rendy 미구현 요소
- 방향키 이동 (10mm/50mm 단위)
- 핸들 크기조절
- SizePanel

## 11. 성능

| 비교 기준 | Rendy | Shin |
|----------|-------|------|
| 배치 성공률 | 100% (slot 제한 적용 시) | ~80% |
| 드랍률 | 0% | ~20% |
| Verification | blocking 0 | blocking 0 |
| E2E 소요 시간 | ~25초 | ~30초 |

---

## Rendy 전체 미구현 요소 목록

| # | 항목 | Phase |
|---|------|-------|
| 1 | 곡선 벽 sagitta 근사 | Phase 4 |
| 2 | 복수 입구 지원 | Phase 4 |
| 3 | MeshStandardMaterial PBR 조명 | Phase 4 |
| 4 | DXF 설비 심볼 매핑 | Phase 4 (샘플 필요) |
| 5 | step_mm ratio / zone 임계값 실측 조정 | Phase 4 |
| 6 | E2E deterministic 테스트 (Agent 3 mock) | Phase 4 |
| 7 | Stateless 서버 (NDA 대응) | 미정 |
| 8 | LLM 수량 판단 (slot hard limit 대체) | 미정 |
| 9 | 레퍼런스 이미지 참조 (Agent 4) | 미정 |
| 10 | 가벽 오브젝트화 | 미정 |
| 11 | 반려 피드백 반영 (사용자 반려 → 재배치) | 미정 |
| 12 | 도미노 검증 구간 (파이프라인 gate) | 미정 |
| 13 | 방향키 이동 / 핸들 크기조절 / SizePanel | 미정 |
| 14 | 배포 설정 | Phase 4 |
