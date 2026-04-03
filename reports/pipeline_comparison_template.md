# 파이프라인 1대1 비교 템플릿

---

## 1. 아키텍처 구조

| 비교 기준 | Rendy | 비교 대상 |
|----------|-------|----------|
| 전체 단계 수 | 4단계 (업로드→감지/마킹→검토→배치) | |
| 백엔드 | FastAPI (Python) | |
| 프론트엔드 | React + Vite + TypeScript | |
| 3D 렌더링 | Three.js (R3F) | |
| AI 모델 | Claude Sonnet 4.5 | |
| DB | Supabase | |
| 모듈 구성 | 에이전트 3 + 모듈 7 + 파서 4 + 스키마 4 | |
| API 수 | 8개 | |
| 처리 방식 | 동기 모놀리식 | |

## 2. 입력 처리

| 비교 기준 | Rendy | 비교 대상 |
|----------|-------|----------|
| 지원 파일 형식 | DXF / PDF / PNG·JPG | |
| 벡터 파일 파싱 방식 | DXF: ezdxf 직접, PDF: pdfplumber 벡터 추출 | |
| 래스터 파일 처리 방식 | OpenCV + Vision AI | |
| 파서 확장 구조 | 어댑터 패턴 (공통 출력 스키마) | |
| 스케일 산출 방식 | 치수선 텍스트 매칭 자동 + 수동 앵커 UI | |
| 단면도 처리 | ceiling_height_mm 추출 (DXF/PDF/Vision) | |

## 3. 공간 분석

| 비교 기준 | Rendy | 비교 대상 |
|----------|-------|----------|
| 좌표계 단위 | mm | |
| 바닥 polygon 추출 | 자동 (파서) + 수동 편집 (마킹 UI) | |
| 배치 불가 영역 처리 | inaccessible rooms + 설비 buffer + inner walls | |
| Zone 분할 방식 | 보행 거리(walk_mm) 기반 동적 경계 | |
| 통로 그래프 | NetworkX 격자 | |
| 비상 통로 모델링 | Main Artery (entrance → farthest point) | |
| 입구 모델링 | 점 → 선분(폭) 확장 + buffer | |

## 4. 브랜드 데이터

| 비교 기준 | Rendy | 비교 대상 |
|----------|-------|----------|
| 브랜드 규정 입력 방식 | PDF 자동 추출 | |
| 추출 방법 | Regex + LLM 라벨링 hybrid | |
| 오브젝트 DB 연동 | Supabase furniture_standards | |
| 쌍 규정(pair rules) 지원 | 분리/합체 규칙, clearspace_mm 거리 검증 | |
| 금지 소재 필터링 | prohibited_material 기반 필터 | |

## 5. 배치 기획 (AI)

| 비교 기준 | Rendy | 비교 대상 |
|----------|-------|----------|
| AI 역할 범위 | zone + direction + priority만 (좌표 금지) | |
| 좌표 계산 주체 | 코드 (Shapely/NetworkX) | |
| 회전 제약 | 직교만 (0/90/180/270) + wall snap | |
| 배치 수 제한 | slot 수 기반 hard limit | |
| 재시도 메커니즘 | Circuit Breaker 3회 | |

## 6. 배치 엔진

| 비교 기준 | Rendy | 비교 대상 |
|----------|-------|----------|
| 충돌 감지 방식 | Shapely polygon intersection | |
| 통로 폭 검증 | 450mm / 1200mm 이원화 | |
| 통로 연결성 검증 | NetworkX has_path (매 배치마다 incremental) | |
| 벽면 정렬(snap) | 최근접 벽 기준 직교 snap (순환 각도 안전) | |
| 관계 제약 검증 | Shapely.distance < clearspace_mm | |
| 증분 검증 | 오브젝트 단위 즉시 | |
| 격자점 탐색 | 법선 방향 다단계 후보 | |

## 7. 실패 처리

| 비교 기준 | Rendy | 비교 대상 |
|----------|-------|----------|
| 실패 분류 방식 | cascade vs physical limit (단독 테스트) | |
| fallback 전략 | deterministic (zone 무시, 전체 slot 순회) | |
| AI 재호출 | 미구현 (고도화 예정) | |
| Graceful Degradation | drop + 사유 명시 | |

## 8. 검증

| 비교 기준 | Rendy | 비교 대상 |
|----------|-------|----------|
| 검증 항목 수 | 5개 | |
| 소방 규정 검증 | 통로 900mm, 비상로 1200mm | |
| 시공 규정 검증 | 벽체 이격 300mm | |
| 결과 분류 | blocking / warning | |

## 9. 출력

| 비교 기준 | Rendy | 비교 대상 |
|----------|-------|----------|
| 3D 모델 포맷 | GLB (trimesh, PBRMaterial) | |
| 비정형 바닥 지원 | extrude_polygon | |
| 텍스트 리포트 | f-string 템플릿 (source별 표기) | |

## 10. 사용자 개입

| 비교 기준 | Rendy | 비교 대상 |
|----------|-------|----------|
| 도면 편집 UI | polygon/설비/inaccessible 드래그 편집 | |
| 스케일 교정 | 수동 앵커 (2점 + mm 입력) | |
| 배치 후 조정 | 3D 드래그/회전 모드 토글 | |

## 11. 성능

| 비교 기준 | Rendy | 비교 대상 |
|----------|-------|----------|
| 배치 성공률 | 100% (slot 제한 적용 시) | |
| 드랍률 | 0% | |
| Verification 결과 | blocking 0 | |
| E2E 소요 시간 | ~25초 (LLM 호출 포함) | |
