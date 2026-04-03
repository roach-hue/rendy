# 파이프라인 1대1 비교 — Rendy vs 우리 (Shin)

> 작성일: 2026-04-03
> 목적: 두 데모 구조의 차이점 분석 → Sprint 3 통합 시 장점 채택

---

## 1. 아키텍처 구조

| 비교 기준 | Rendy | Shin (우리) |
|----------|-------|------------|
| 전체 단계 수 | 4단계 (업로드→감지/마킹→검토→배치) | 5단계 (업로드→감지/마킹→에어리얼확인→배치→3D편집) |
| 백엔드 | FastAPI (Python) | FastAPI (Python) |
| 프론트엔드 | React + Vite + TypeScript | Next.js + TypeScript |
| 3D 렌더링 | Three.js (R3F) | Three.js (@react-three/fiber + drei) |
| AI 모델 | Claude Sonnet 4.5 | Claude Sonnet 4.6 |
| DB | Supabase | 미사용 (stateless — NDA 대응) |
| 모듈 구성 | 에이전트 3 + 모듈 7 + 파서 4 + 스키마 4 | Agent 3 + 엔진 2(Shapely/NetworkX) + 파서 1 + 레퍼런스 1 |
| API 수 | 8개 | 6개 (/detect, /extract, /calculate, /place, /validate, /reject) |
| 처리 방식 | 동기 모놀리식 | Agent1+2a 병렬 → 2b 순차 → 3 순차 |

## 2. 입력 처리

| 비교 기준 | Rendy | Shin (우리) |
|----------|-------|------------|
| 지원 파일 형식 | DXF / PDF / PNG·JPG | PDF only (벡터+래스터) |
| 벡터 파일 파싱 방식 | DXF: ezdxf 직접, PDF: pdfplumber 벡터 추출 | PDF: pymupdf get_drawings() → Shapely polygonize |
| 래스터 파일 처리 방식 | OpenCV + Vision AI | OpenCV contour + Vision API polygon 감지 |
| 파서 확장 구조 | 어댑터 패턴 (공통 출력 스키마) | 4중 방어 (polygonize → drawing별 → Vision → 수동) |
| 스케일 산출 방식 | 치수선 텍스트 매칭 자동 + 수동 앵커 UI | 치수선 텍스트 최대값 자동 + 수동 입력 |
| 단면도 처리 | ceiling_height_mm 추출 (DXF/PDF/Vision) | 미처리 (평면도만) |

## 3. 공간 분석

| 비교 기준 | Rendy | Shin (우리) |
|----------|-------|------------|
| 좌표계 단위 | mm | mm |
| 바닥 polygon 추출 | 자동 (파서) + 수동 편집 (마킹 UI) | 자동 (polygonize 1순위) + Vision fallback + 수동 예정 |
| 배치 불가 영역 처리 | inaccessible rooms + 설비 buffer + inner walls | Dead Zone (SP 900mm/FH 1000mm/EP 600mm) + 입구 exclusion |
| Zone 분할 방식 | 보행 거리(walk_mm) 기반 동적 경계 | 보행 거리 기반 zone_label (entrance/near/mid/deep) |
| 통로 그래프 | NetworkX 격자 | NetworkX 격자 (300mm 간격) |
| 비상 통로 모델링 | Main Artery (entrance → farthest point) | 경로 존재 확인 (정밀 폭 검증은 단순화) |
| 입구 모델링 | 점 → 선분(폭) 확장 + buffer | 점/선분/polyline + 폭 비례 exclusion (1200/800/500mm) |

## 4. 브랜드 데이터

| 비교 기준 | Rendy | Shin (우리) |
|----------|-------|------------|
| 브랜드 규정 입력 방식 | PDF 자동 추출 | PDF 자동 추출 |
| 추출 방법 | Regex + LLM 라벨링 hybrid | LLM only (Claude) + Pydantic 검증 |
| 오브젝트 DB 연동 | Supabase furniture_standards | 미사용 (placement_rules에서 직접 추출) |
| 쌍 규정(pair rules) 지원 | 분리/합체 규칙, clearspace_mm 거리 검증 | relationships 자연어 + min_clearspace_mm |
| 금지 소재 필터링 | prohibited_material 기반 필터 | prohibited_material 기반 필터 |

## 5. 배치 기획 (AI)

| 비교 기준 | Rendy | Shin (우리) |
|----------|-------|------------|
| AI 역할 범위 | zone + direction + priority만 (좌표 금지) | ref_point + direction + priority + 수량 (좌표 금지) |
| 좌표 계산 주체 | 코드 (Shapely/NetworkX) | 코드 (Shapely/NetworkX) |
| 회전 제약 | 직교만 (0/90/180/270) + wall snap | wall_facing: wall_angle_deg 자동 / freestanding: 45도 단위 |
| 배치 수 제한 | slot 수 기반 hard limit | 벽 수용량 상한 + LLM 자유 판단 (60~70% 활용 가이드) |
| 재시도 메커니즘 | Circuit Breaker 3회 | 코드 조정(±100mm 8방향) → 대안 ref → LLM 재호출 1회 |

## 6. 배치 엔진

| 비교 기준 | Rendy | Shin (우리) |
|----------|-------|------------|
| 충돌 감지 방식 | Shapely polygon intersection | Shapely polygon intersection + buffer(gap_mm) |
| 통로 폭 검증 | 450mm / 1200mm 이원화 | 경로 존재만 (데모 단순화, erode 방식은 과잉 차단 문제) |
| 통로 연결성 검증 | NetworkX has_path (매 배치마다 incremental) | NetworkX shortest_path (배치마다 체크) |
| 벽면 정렬(snap) | 최근접 벽 기준 직교 snap (순환 각도 안전) | wall_angle_deg 기반 자동 회전 (wall_facing만) |
| 관계 제약 검증 | Shapely.distance < clearspace_mm | placement_rules 하네스 (preferred_wall, required_direction 강제) |
| 증분 검증 | 오브젝트 단위 즉시 | 오브젝트 단위 즉시 (placed_polygons 누적) |
| 격자점 탐색 | 법선 방향 다단계 후보 | 8방향 ±100mm × 10스텝 + 대안 ref 순회 |

## 7. 실패 처리

| 비교 기준 | Rendy | Shin (우리) |
|----------|-------|------------|
| 실패 분류 방식 | cascade vs physical limit (단독 테스트) | out_of_floor / dead_zone_collision / shapely_collision / corridor_blocked |
| fallback 전략 | deterministic (zone 무시, 전체 slot 순회) | 코드 조정 → 대안 ref → LLM 재호출 (3단계) |
| AI 재호출 | 미구현 (고도화 예정) | 구현 (최대 1회, 실패 사유 + 점유 현황 전달) |
| Graceful Degradation | drop + 사유 명시 | violation warning 기록 + 배치 가능한 것만 표시 |

## 8. 검증

| 비교 기준 | Rendy | Shin (우리) |
|----------|-------|------------|
| 검증 항목 수 | 5개 | 3개 (바닥 이탈, dead zone 충돌, 오브젝트 충돌) |
| 소방 규정 검증 | 통로 900mm, 비상로 1200mm | 입구 exclusion 1200mm, 통로 경로 존재 확인 |
| 시공 규정 검증 | 벽체 이격 300mm | wall_clearance 300mm + object_gap 300mm |
| 결과 분류 | blocking / warning | blocking / warning (pass 시 "배치 검증 통과") |

## 9. 출력

| 비교 기준 | Rendy | Shin (우리) |
|----------|-------|------------|
| 3D 모델 포맷 | GLB (trimesh, PBRMaterial) | GLB (Three.js GLTFExporter) |
| 비정형 바닥 지원 | extrude_polygon | ShapeGeometry (2D polygon → 3D 바닥) |
| 텍스트 리포트 | f-string 템플릿 (source별 표기) | 미구현 (Agent 5 MVP 예정) |

## 10. 사용자 개입

| 비교 기준 | Rendy | Shin (우리) |
|----------|-------|------------|
| 도면 편집 UI | polygon/설비/inaccessible 드래그 편집 | 입구 polyline + 설비 클릭 마킹 + "다시 인식" 버튼 |
| 스케일 교정 | 수동 앵커 (2점 + mm 입력) | 수동 mm/px 입력 (1점) |
| 배치 후 조정 | 3D 드래그/회전 모드 토글 | 방향키 이동 + 드래그 이동 + 핸들 크기조절 + 45도 회전 + SizePanel |

## 11. 성능

| 비교 기준 | Rendy | Shin (우리) |
|----------|-------|------------|
| 배치 성공률 | 100% (slot 제한 적용 시) | ~80% (Vision polygon 오인 시 하락) |
| 드랍률 | 0% | ~20% (corridor/out_of_floor로 deferred) |
| Verification 결과 | blocking 0 | blocking 0 (violation은 warning으로 처리) |
| E2E 소요 시간 | ~25초 (LLM 호출 포함) | ~30초 (LLM 2~3회 + Tavily 검색 포함) |

---

## 비교 분석

### Rendy가 앞서는 점

| 항목 | 내용 | 우리에게 시사점 |
|------|------|---------------|
| **DXF 직접 지원** | ezdxf로 DXF 원본 파싱 → PDF 변환 불필요 | DXF 지원 추가하면 벡터 정확도 상승 |
| **Supabase DB 연동** | furniture_standards 테이블 → 규격 DB화 | Sprint 3~4에서 필요 |
| **통로 폭 이원화** | 450mm(보조)/1200mm(비상) 구분 검증 | 우리는 경로 존재만 확인 (단순화) |
| **어댑터 패턴 파서** | DXF/PDF/이미지 → 공통 스키마 | 파서 확장 시 참고 |
| **배치 성공률 100%** | slot 제한으로 항상 성공 보장 | 우리는 LLM 의존으로 실패 가능 |
| **Regex+LLM hybrid 추출** | 정규식으로 수치 잡고 LLM은 라벨링만 | 추출 정확도 향상 가능 |
| **쌍 규정(pair rules)** | "A와 B를 N mm 이상 떨어뜨려라" 구조화 | relationships 고도화 시 참고 |

### 우리가 앞서는 점

| 항목 | 내용 | Rendy에게 시사점 |
|------|------|---------------|
| **Stateless 서버 (NDA 대응)** | 브랜드 데이터 저장 0 → 실서비스 가능 | DB에 브랜드 규정 저장하면 NDA 문제 |
| **LLM 수량 판단** | 코드 상한 + LLM 자유 결정 (설계 의도 반영) | slot hard limit은 기계적 |
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
| 통로 폭 이원화 (450/1200) | 소방법 정밀 준수 |
| Supabase furniture_standards | 오브젝트 규격 DB화 (하드코딩 탈피) |
| Regex+LLM hybrid 추출 | 매뉴얼 수치 추출 정확도 향상 |
| 어댑터 패턴 파서 | 다양한 입력 포맷 확장 |

| 우리 것 유지할 것 | 이유 |
|-----------------|------|
| Stateless 서버 | NDA 대응 — 서비스 핵심 요건 |
| polygonize 1순위 | CAD 형식 무관 범용성 |
| LLM 수량 판단 | 설계 의도 반영 (slot hard limit은 기계적) |
| 도미노 검증 구간 | 연쇄 실패 방지 — 안정성 핵심 |
| 3D 편집 상세 | 사용자 미세조정 — UX 핵심 |
| 레퍼런스 이미지 | 배치 컨셉 다양화 |
