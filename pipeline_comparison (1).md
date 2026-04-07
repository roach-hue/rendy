# 파이프라인 1대1 비교 — Rendy vs 우리 (Shin)

> 최종 갱신: 2026-04-07
> 목적: 두 데모 구조의 차이점 분석 → Sprint 3 통합 시 장점 채택

---

## 1. 아키텍처 구조

| 비교 기준 | Rendy | Shin (우리) |
|----------|-------|------------|
| 전체 단계 수 | 4단계 (업로드→감지/마킹→검토→배치) | 5단계 (업로드→감지/마킹→에어리얼확인→배치→3D편집) |
| 백엔드 | FastAPI (Python) | FastAPI (Python) |
| 프론트엔드 | React + Vite + TypeScript | Next.js + TypeScript |
| 3D 렌더링 | Three.js (R3F + drei + Html labels) | Three.js (@react-three/fiber + drei) |
| AI 모델 | Claude Sonnet 4.5 | Claude Sonnet 4.6 |
| DB | Supabase (furniture_standards + geometry_cache) | 미사용 (stateless — NDA 대응) |
| 모듈 구성 | 에이전트 3 + 모듈 10 + 파서 4 + 스키마 5 (37 파일) | Agent 3 + 엔진 2(Shapely/NetworkX) + 파서 1 + 레퍼런스 1 |
| API 수 | 8개 | 6개 (/detect, /extract, /calculate, /place, /validate, /reject) |
| 처리 방식 | 동기 모놀리식 + 배치 결과 캐시 (동일 도면 LLM 0회) | Agent1+2a 병렬 → 2b 순차 → 3 순차 |

## 2. 입력 처리

| 비교 기준 | Rendy | Shin (우리) |
|----------|-------|------------|
| 지원 파일 형식 | DXF / DWG(ODA 경유) / PDF / PNG·JPG | PDF only (벡터+래스터) |
| 벡터 파일 파싱 방식 | DXF: ezdxf (ARC/CIRCLE tessellation, LWPOLYLINE bulge, TEXT/MTEXT 앵커링, 설비 심볼 추출) | PDF: pymupdf get_drawings() → Shapely polygonize |
| 래스터 파일 처리 방식 | OpenCV + Vision AI | OpenCV contour + Vision API polygon 감지 |
| 파서 확장 구조 | 어댑터 패턴 (FloorPlanParser 추상 → DXF/DWG/PDF/Image 4종, 공통 ParsedDrawings 스키마) | 4중 방어 (polygonize → drawing별 → Vision → 수동) |
| 스케일 산출 방식 | 치수선 텍스트 매칭 자동 + 수동 앵커 UI (2점 + mm) | 치수선 텍스트 최대값 자동 + 수동 입력 |
| 단면도 처리 | ceiling_height_mm 추출 (DXF/PDF/Vision) | 미처리 (평면도만) |

## 3. 공간 분석

| 비교 기준 | Rendy | Shin (우리) |
|----------|-------|------------|
| 좌표계 단위 | mm (Y-up 통일) | mm |
| 바닥 polygon 추출 | 자동 (파서) + 수동 편집 (마킹 UI) | 자동 (polygonize 1순위) + Vision fallback + 수동 예정 |
| 배치 불가 영역 처리 | inaccessible rooms + 설비 buffer (SP 300/FH 500/EP 600mm) + inner walls + entrance buffer 460mm | Dead Zone (SP 900mm/FH 1000mm/EP 600mm) + 입구 exclusion |
| Zone 분할 방식 | walk_mm 기반 동적 경계 + 복수 입구 min(거리) 대응 (zone_label은 MAIN 기준 단방향 유지) | 보행 거리 기반 zone_label (entrance/near/mid/deep) |
| 슬롯 메타데이터 | walk_mm + zone_label + spine_rank(adjacent/nearby/far) + semantic_tags(corner/wall_adjacent/center_area/entrance_facing) + shelf_capacity | walk_mm + zone_label |
| 통로 그래프 | NetworkX 격자 (500mm 간격, Choke Point 병목 탐지) | NetworkX 격자 (300mm 간격) |
| 주동선 모델링 | VMD Main Spine — 입구→바닥중심→최원벽면 직각(ㄱ자) 경로. 복수 입구 시 MAIN→deep wall→EXIT 관통 동선 | 경로 존재 확인 (정밀 폭 검증은 단순화) |
| 부동선 모델링 | Sub-path — Spine 종점→미커버 기물 경유→외곽 fallback→입구 복귀 루프 (100% 생성 보장) | 없음 |
| 입구 모델링 | 점 → 선분(폭) 확장 + buffer 460mm, 복수 입구 전체 buffer 병합, 3D 바닥 데칼 표시 | 점/선분/polyline + 폭 비례 exclusion (1200/800/500mm) |

## 4. 브랜드 데이터

| 비교 기준 | Rendy | Shin (우리) |
|----------|-------|------------|
| 브랜드 규정 입력 방식 | PDF 자동 추출 | PDF 자동 추출 |
| 추출 방법 | Regex + LLM 라벨링 hybrid | LLM only (Claude) + Pydantic 검증 |
| 오브젝트 DB 연동 | Supabase furniture_standards + Generative Asset Provisioning (Agent 3 제안 기물 자동 DB INSERT) | 미사용 (placement_rules에서 직접 추출) |
| 쌍 규정(pair rules) 지원 | 분리/합체 규칙, clearspace_mm 거리 검증 | relationships 자연어 + min_clearspace_mm |
| 금지 소재 필터링 | prohibited_material 기반 필터 | prohibited_material 기반 필터 |

## 5. 배치 기획 (AI)

| 비교 기준 | Rendy | Shin (우리) |
|----------|-------|------------|
| AI 역할 범위 | zone + direction + priority + alignment + placed_because (좌표 금지) | ref_point + direction + priority + 수량 (좌표 금지) |
| 동선 인식 | Agent 3에 Spine 구조(경유점+방향) + 슬롯별 spine_rank 전달. P4 규칙: Hero는 adjacent에만, 보조는 far 허용 | 없음 |
| 좌표 계산 주체 | 코드 (Shapely/NetworkX) | 코드 (Shapely/NetworkX) |
| 회전 제약 | wall_angle_deg 자동 + alignment(parallel/perpendicular/opposite/none) | wall_facing: wall_angle_deg 자동 / freestanding: 45도 단위 |
| 배치 수 제한 | IQI 밀도 제한 (면적 25% 상한) + slot 수 기반 hard limit | 벽 수용량 상한 + LLM 자유 판단 (60~70% 활용 가이드) |
| 프롬프트 최적화 | 대규모 슬롯 통계 요약 (2500슬롯→50줄, zone×spine 분포 + 대표 샘플) | 전체 슬롯 나열 |
| 재시도 메커니즘 | Circuit Breaker 3회 + Choke Point 피드백 f-string | 코드 조정(±100mm 8방향) → 대안 ref → LLM 재호출 1회 |

## 6. 배치 엔진

| 비교 기준 | Rendy | Shin (우리) |
|----------|-------|------------|
| 슬롯 정렬 전략 | direction 분기: wall_facing→far 우선(반대편 분산), inward/center→adjacent 우선(Spine 집중) | walk_mm 오름차순 |
| 충돌 감지 방식 | Shapely polygon intersection + join_pair 겹침 허용(면적 20% 미만) | Shapely polygon intersection + buffer(gap_mm) |
| 통로 폭 검증 | Main Artery 600mm + 일반 통로 450mm 이원화, static_cache union | 경로 존재만 (데모 단순화, erode 방식은 과잉 차단 문제) |
| 통로 연결성 검증 | NetworkX has_path (매 배치마다 incremental, 장애물 buffer 내 노드 제거) | NetworkX shortest_path (배치마다 체크) |
| 벽면 정렬(snap) | 최근접 벽 기준 직교 snap (순환 각도 안전) | wall_angle_deg 기반 자동 회전 (wall_facing만) |
| 관계 제약 검증 | Shapely.distance < clearspace_mm + 분리 키워드 감지 | placement_rules 하네스 (preferred_wall, required_direction 강제) |
| 증분 검증 | 오브젝트 단위 즉시 + Choke Point 동선 병목 900mm 검증 | 오브젝트 단위 즉시 (placed_polygons 누적) |
| IQI 밀도 체크 | 배치 도중 cumulative_footprint 실시간 25% 상한 | 없음 |

## 7. 실패 처리

| 비교 기준 | Rendy | Shin (우리) |
|----------|-------|------------|
| 실패 분류 방식 | cascade vs physical limit (단독 테스트) + failure_classifier (동선 병목/슬롯 부족 분리) | out_of_floor / dead_zone_collision / shapely_collision / corridor_blocked |
| fallback 전략 | 3단계: 정상→Global Reset(Choke Point 피드백)→Deterministic Fallback(zone 무시 전체 순회) | 코드 조정 → 대안 ref → LLM 재호출 (3단계) |
| AI 재호출 | 구현됨 (최대 2회, Choke Point intersects f-string 피드백 전달) | 구현 (최대 1회, 실패 사유 + 점유 현황 전달) |
| Graceful Degradation | drop + 사유 명시 + source:"fallback" 표기 | violation warning 기록 + 배치 가능한 것만 표시 |

## 8. 검증

| 비교 기준 | Rendy | Shin (우리) |
|----------|-------|------------|
| 검증 항목 수 | 5개 | 3개 (바닥 이탈, dead zone 충돌, 오브젝트 충돌) |
| 소방 규정 검증 | 통로 900mm, 비상로 1200mm, Choke Point 병목 | 입구 exclusion 1200mm, 통로 경로 존재 확인 |
| 시공 규정 검증 | 벽체 이격 300mm | wall_clearance 300mm + object_gap 300mm |
| 결과 분류 | blocking / warning | blocking / warning (pass 시 "배치 검증 통과") |

## 9. 출력

| 비교 기준 | Rendy | Shin (우리) |
|----------|-------|------------|
| 3D 모델 포맷 | GLB (trimesh, PBRMaterial) + InstancedMesh (geometry_id 그룹화) | GLB (Three.js GLTFExporter) |
| 비정형 바닥 지원 | extrude_polygon + Y↔Z swap matrix | ShapeGeometry (2D polygon → 3D 바닥) |
| 깊이 정밀도 | logarithmicDepthBuffer (near=10, far=100000) | 기본 |
| 동선 시각화 | Main Spine(핑크 리본) + Sub-path(초록 라인) + 입구 데칼(링+십자) + Zone Disc | 없음 |
| 오브젝트 라벨 | ON/OFF 토글, 영어 PascalCase (Html overlay) | 없음 |
| 텍스트 리포트 | f-string 템플릿 (source별 표기, placed_because, 조정 이력, 면책) | 미구현 (Agent 5 MVP 예정) |

## 10. 사용자 개입

| 비교 기준 | Rendy | Shin (우리) |
|----------|-------|------------|
| 도면 편집 UI | polygon/설비/inaccessible/입구 드래그 편집 + 확대/축소 (+/-/초기화) | 입구 polyline + 설비 클릭 마킹 + "다시 인식" 버튼 |
| 스케일 교정 | 수동 앵커 (2점 + mm 입력) | 수동 mm/px 입력 (1점) |
| 배치 후 조정 | 3D 드래그/회전 모드 토글 | 방향키 이동 + 드래그 이동 + 핸들 크기조절 + 45도 회전 + SizePanel |
| 배치 캐시 | 동일 도면 hash → 캐시 히트 시 LLM 0회 (~0.1초) | 없음 |

## 11. 성능

| 비교 기준 | Rendy | Shin (우리) |
|----------|-------|------------|
| 배치 성공률 | 100% (IQI + slot 제한 + fallback) | 100% (오브젝트 간 좌표 충돌은 별도 이슈) |
| 드랍률 | 0% | 0% |
| Verification 결과 | blocking 0, warning 0~1 | blocking 0 (violation은 warning으로 처리) |
| E2E 소요 시간 | 캐시 미스: ~60초 (LLM 1회), 캐시 히트: ~0.1초 | ~30초 (LLM 2~3회 + Tavily 검색 포함) |

---

## 비교 분석

### Rendy가 앞서는 점

| 항목 | 내용 | 우리에게 시사점 |
|------|------|---------------|
| **DXF 직접 지원 + 어댑터 4종** | ezdxf로 ARC/CIRCLE/bulge/TEXT 원본 파싱, DWG/PDF/Image 확장 | DXF 지원 추가하면 벡터 정확도 상승 |
| **VMD 주동선(Main Spine)** | 입구→deep wall 직각 동선 선행 → 배치가 동선 종속 | 동선 없이 배치하면 기물 방향성 무작위 |
| **spine_rank 배치 분산** | Hero→adjacent, 선반→far 분기 정렬. 매장 양쪽 벽면 균등 활용 | 슬롯 정렬 전략 없으면 한쪽 편중 |
| **부동선 복귀 루프** | 기물 경유 + 외곽 fallback, 100% 생성 보장 | 순환 동선 없으면 단방향 사각지대 |
| **Supabase + GAP** | furniture_standards DB + Agent 3 제안 기물 자동 INSERT | Sprint 3~4에서 필요 |
| **통로 폭 이원화** | 450mm(보조)/600mm(Main Artery) 구분, Choke Point 병목 검증 | 우리는 경로 존재만 확인 (단순화) |
| **Regex+LLM hybrid 추출** | 정규식으로 수치 잡고 LLM은 라벨링만 | 추출 정확도 향상 가능 |
| **배치 캐시** | 동일 도면 hash → LLM 0회, 0.1초 응답 | 반복 테스트 비용 절감 |
| **프롬프트 토큰 최적화** | 2500슬롯→50줄 통계 요약 | rate limit 회피, 비용 절감 |
| **IQI 밀도 제한** | 면적 25% 상한 실시간 체크 | 과밀 배치 방지 |

### 우리가 앞서는 점

| 항목 | 내용 | Rendy에게 시사점 |
|------|------|---------------|
| **Stateless 서버 (NDA 대응)** | 브랜드 데이터 저장 0 → 실서비스 가능 | DB에 브랜드 규정 저장하면 NDA 문제 |
| **LLM 수량 판단** | 코드 상한 + LLM 자유 결정 (설계 의도 반영) | IQI hard limit은 기계적일 수 있음 |
| **레퍼런스 이미지 참고** | Tavily 조감도 → LLM Vision 참고 | 배치 컨셉 다양화 |
| **가벽 오브젝트화** | 3D에서 이동/크기조절/회전 + 양면 ref_point | dead zone보다 실용적 |
| **3D 편집 상세** | 방향키(10/50mm) + 드래그(1mm snap) + SizePanel | 배치 후 미세조정 가능 |
| **Agent1+2a 병렬 실행** | 매뉴얼 추출과 도면 감지 동시 | 응답 시간 단축 |
| **polygonize 범용 파싱** | CAD item 타입 무관 → 형식 의존도 낮음 | pdfplumber보다 범용적일 수 있음 |
| **도미노 검증 구간** | 파이프라인 2곳에 gate → 잘못된 데이터 조기 차단 | 연쇄 실패 방지 |
| **반려 피드백 반영** | 사용자 반려 사유가 재배치에 전달 | 맹목적 재시도가 아닌 학습형 |

### 통합 시 채택 검토 대상

| Rendy에서 가져올 것 | 이유 |
|-------------------|------|
| DXF 직접 지원 (ezdxf) | PDF 변환 과정에서 정보 손실 방지 |
| VMD 주동선 + spine_rank 배치 | 동선 기반 배치 = VMD 정석 |
| 통로 폭 이원화 (450/600) + Choke Point | 소방법 정밀 준수 |
| Supabase furniture_standards + GAP | 오브젝트 규격 DB화 (하드코딩 탈피) |
| Regex+LLM hybrid 추출 | 매뉴얼 수치 추출 정확도 향상 |
| 어댑터 패턴 파서 (공통 스키마) | 다양한 입력 포맷 확장 |
| 배치 캐시 + 프롬프트 최적화 | 비용/속도 절감 |
| IQI 밀도 제한 | 과밀 배치 방지 |

| 우리 것 유지할 것 | 이유 |
|-----------------|------|
| Stateless 서버 | NDA 대응 — 서비스 핵심 요건 |
| polygonize 1순위 | CAD 형식 무관 범용성 |
| LLM 수량 판단 | 설계 의도 반영 (slot hard limit은 기계적) |
| 도미노 검증 구간 | 연쇄 실패 방지 — 안정성 핵심 |
| 3D 편집 상세 | 사용자 미세조정 — UX 핵심 |
| 레퍼런스 이미지 | 배치 컨셉 다양화 |
| 반려 피드백 반영 | 학습형 재시도 |
