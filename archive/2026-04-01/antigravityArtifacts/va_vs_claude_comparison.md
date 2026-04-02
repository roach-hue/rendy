# 구 va vs 신규 .claude/ 구조 비교표

> 비교 대상:
> - **구**: `old/_Agent_IO_._va.md` (원본 I/O 흐름 구조)
> - **신**: `.claude/agents/` + `.claude/skills/` + `architecture_spec.md` (현재 확정 구조)

---

## 1. 전체 파이프라인

| 단계 | 구 va | 신 .claude/ | 상태 |
|------|-------|-------------|------|
| 입력 화면 | 도면 + 메뉴얼 동시 업로드 | 동일 | 동일 |
| Agent 1 | LLM 단독 추출 | **Regex + LLM hybrid** | 🟡 변경 |
| 브랜드 확인 UI | 입력 화면에서 확인 | 동일 | 동일 |
| Agent 2 전반부 | LLM + 코드 (감지만) | 동일 | 동일 |
| 사용자 마킹 | 감지 결과 수정 + 설비 추가 | 동일 | 동일 |
| Agent 2 후반부 | Dead Zone + NetworkX 계산 | 동일 + **zone polygon 경계** + **wall_linestring** + **자연어 요약 생성** | 🟡 변경 |
| 1단계 확인 UI | 계산 결과 확인 | 동일 | 동일 |
| 오브젝트 선별 | 코드 (Supabase 조회) | 동일 | 동일 |
| Agent 3 | LLM — **reference_point** 직접 지정 | LLM — **zone_label만** 지정 | 🔴 변경 |
| 코드 순회 루프 | 100mm씩 위치 조정 | **격자점 순회 + buffer(450) 근사 + NetworkX 최종 1회** | 🔴 변경 |
| 검증 모듈 | blocking이면 차단 (기준 미명시) | blocking 기준 3개 명시 (900mm/1200mm/Dead Zone) | 🟡 변경 |
| .glb 생성 | Three.js Whitebox → .glb | 동일 | 동일 |
| Agent 4 | MVP 후순위 (레이아웃 검토) | **삭제** | 🔴 삭제 |
| Agent 5 | 템플릿 → LLM (이후) | **f-string 템플릿 고정** (LLM 전환 계획 없음) | 🟡 변경 |

---

## 2. Agent 1 — 브랜드 수치 추출

| 항목 | 구 va | 신 .claude/ | 상태 |
|------|-------|-------------|------|
| 처리 방식 | LLM 단독 (Claude Document API) | **텍스트 PDF → Regex 기계 추출 + LLM 라벨링** / 이미지 PDF → Vision | 🔴 변경 |
| 추출 대상 5개 | clearspace, orientation, material, logo, relationships | 동일 | 동일 |
| 필드 래핑 | `{value, confidence, source}` | 동일 | 동일 |
| null 처리 | DEFAULTS merge + source: "default" | 동일 | 동일 |
| Pydantic validator | 300~5000 범위 | 동일 | 동일 |
| 소방/시공 하드코딩 | fire, construction dict | 동일 | 동일 |
| Regex 전처리 | 없음 | **신규** — LLM 환각 방지 | 🟢 신규 |
| agent 파일 | 없음 | `agent-1-brand-extraction.md` | 🟢 신규 |
| skill 파일 | 없음 | `brand_extraction.md` | 🟢 신규 |

---

## 3. Agent 2 전반부 — 도면 감지

| 항목 | 구 va | 신 .claude/ | 상태 |
|------|-------|-------------|------|
| OpenCV polygon | 있음 | 동일 | 동일 |
| OCR 치수선 | 있음 | 동일 | 동일 |
| Claude Vision | 입구+스프링클러+소화전+분전반 동시 감지 | 동일 | 동일 |
| auto_detected 구조 | scale_confidence 포함 | scale_confidence **미포함** | 🟡 변경 |
| 파서 어댑터 패턴 | 없음 | **FloorPlanParser 추상 클래스** (DWG/PDF/Image) | 🟢 신규 |
| Vision 프롬프트 가이드 | 없음 | **skill에 프롬프트 템플릿 포함** | 🟢 신규 |
| agent 파일 | 없음 | `agent-2-floorplan.md` | 🟢 신규 |
| skill 파일 | 없음 | `floorplan_detection.md` | 🟢 신규 |

---

## 4. Agent 2 후반부 — 공간 연산

| 항목 | 구 va | 신 .claude/ | 상태 |
|------|-------|-------------|------|
| 픽셀→mm 변환 | 있음 | 동일 | 동일 |
| Dead Zone 생성 | 있음 | 동일 | 동일 |
| reference_point | x_mm, y_mm 좌표만 | + **wall_linestring** + **wall_normal** + **zone_label** | 🔴 변경 |
| zone polygon 경계 | 없음 | **Shapely Polygon으로 명시적 저장** | 🟢 신규 |
| NetworkX | 격자 그래프 + 보행 거리 | 동일 | 동일 |
| Agent 3용 자연어 요약 | zone_label + shelf_capacity 저장 | 동일 + **명시적 요약 문자열 생성** | 🟡 변경 |
| 벽 표현 | 암묵적 (좌표만) | **LineString 객체** (Issue 8) | 🔴 변경 |
| skill 파일 | 없음 | `spatial_computation.md` | 🟢 신규 |

---

## 5. Agent 3 — 배치 기획

| 항목 | 구 va | 신 .claude/ | 상태 |
|------|-------|-------------|------|
| Output 핵심 필드 | `reference_point` (직접 지정) | **`zone_label`** (구역만 지정) | 🔴 변경 |
| direction | wall_facing, inward, outward, center (4개 활성) | wall_facing, inward, center (**outward 더미 처리**) | 🟡 변경 |
| 재호출 피드백 | placed_objects JSON + alternative_references | **Choke Point intersects f-string 요약문만** | 🔴 변경 |
| 재호출 상한 | 최대 2회 (Shapely 실패) + Circuit Breaker 3회 (Pydantic) | **zone 소진 시 자연 종료** (zone 수 = 최대 재호출) | 🔴 변경 |
| Pydantic 스키마 | reference_point 필드 있음 | **zone_label 필드로 교체** | 🔴 변경 |
| placed_because | 있음 | 동일 + **코드 조정 시 이력 추가** | 🟡 변경 |
| agent 파일 | 없음 | `agent-3-placement.md` | 🟢 신규 |
| skill 파일 | 없음 | `placement_planning.md` | 🟢 신규 |

---

## 6. 코드 순회 루프 + 배치 검증

| 항목 | 구 va | 신 .claude/ | 상태 |
|------|-------|-------------|------|
| 위치 조정 방식 | 100mm씩 이동 (step_mm 고정 암시) | **격자점 순회** (step_mm = √(w²+d²) × ratio 동적) | 🔴 변경 |
| 순회 범위 | zone 범위 불명확 | **zone_polygon.contains() 선행 체크** | 🟢 신규 |
| 충돌 검증 | Shapely + NetworkX 동시 | **buffer(450) 근사 먼저 + NetworkX 최종 1회** | 🔴 변경 |
| calculate_position | 암묵적 (dict 좌표 직접 조회) | **명시적 함수 분리** (LineString + 수선의 발) | 🔴 변경 |
| cascade failure | 없음 (Agent 3 재호출 2회로 대응) | **Global Reset + Choke Point intersects 원인 추출** | 🟢 신규 |
| 물리적 한계 | 없음 | **단독 배치 테스트 → Graceful Degradation** | 🟢 신규 |
| 관계 제약 검증 | 없음 (Agent 3에 위임) | **zone_label 비교로 코드 검증** | 🟢 신규 |
| 격자점 0개 fallback | 없음 | **중앙 + 양 끝 3점** | 🟢 신규 |
| 가상 입구 선분 | 없음 | **offset_curve (450+10)mm** | 🟢 신규 |
| 캐시 생명주기 | 없음 | **static_buffered_obstacles 캐시 + Global Reset 시 파기** | 🟢 신규 |

---

## 7. 검증 모듈

| 항목 | 구 va | 신 .claude/ | 상태 |
|------|-------|-------------|------|
| blocking 기준 | "blocking이면 차단" (구체 기준 없음) | **소방 900mm + 비상 1200mm + Dead Zone 침범** 명시 | 🔴 변경 |
| warning 분리 | 없음 | **벽체 이격 등 warning은 .glb 허용** | 🟢 신규 |
| 검증 결과 구조 | 불명확 | **checks 배열 + warning 배열 구조화** | 🟢 신규 |
| skill 파일 | 없음 | `placement_verification.md` | 🟢 신규 |

---

## 8. Agent 4 — 레이아웃 검토

| 항목 | 구 va | 신 .claude/ | 상태 |
|------|-------|-------------|------|
| 존재 | MVP 후순위로 존재 | **삭제** | 🔴 삭제 |

---

## 9. Agent 5 — 리포트

| 항목 | 구 va | 신 .claude/ | 상태 |
|------|-------|-------------|------|
| 방식 | 템플릿 (MVP) → LLM 전환 예정 | **f-string 템플릿 고정** (LLM 전환 계획 없음) | 🟡 변경 |
| 포함 내용 | source별 표기 + 면책 조항 | 동일 + **코드 조정 이력** + **배치 불가 목록+사유** | 🟡 변경 |
| agent 파일 | 없음 | `agent-5-report.md` | 🟢 신규 |
| skill 파일 | 없음 | `report.md` | 🟢 신규 |

---

## 10. 데이터 구조 (space_data)

| 항목 | 구 va | 신 .claude/ | 상태 |
|------|-------|-------------|------|
| reference_point | x_mm, y_mm만 | + **wall_linestring** + **wall_normal** + **zone_label** + **shelf_capacity** | 🔴 변경 |
| zone 경계 | 없음 (암묵적) | **Shapely Polygon 명시적 저장** | 🟢 신규 |
| sprinkler 표현 | center_mm + radius_mm | 동일 (구조 변화 없음) | 동일 |
| 소방/시공 | fire + construction dict | 동일 | 동일 |
| disclaimer | `auto_detected`에 저장 | `space_data["infra"]["disclaimer"]`에 저장 | 동일 |

---

## 11. 실패 처리

| 실패 유형 | 구 va | 신 .claude/ | 상태 |
|-----------|-------|-------------|------|
| 추출 실패 | null → 기본값 | 동일 | 동일 |
| 감지 실패 | 사용자 마킹 + 면책 | 동일 | 동일 |
| 배치 실패 — 코드 조정 | 100mm씩 이동 (최대 10회 암시) | **격자 순회 (zone 반경 기반 동적)** | 🔴 변경 |
| 배치 실패 — Agent 재호출 | 최대 2회 + placed_objects 전달 | **Global Reset + Choke Point 요약문만 전달 + zone 소진 종료** | 🔴 변경 |
| 물리적 한계 | 없음 | **단독 배치 테스트 → Graceful Degradation** | 🟢 신규 |
| 관계 제약 위반 | 없음 (검출 못함) | **zone_label 비교 → Agent 3 재호출** | 🟢 신규 |
| 스키마 실패 | Circuit Breaker 3회 | 동일 | 동일 |

---

## 12. 인프라/설정

| 항목 | 구 va | 신 .claude/ | 상태 |
|------|-------|-------------|------|
| .claude/agents/ | 없음 | **4개 agent 파일** | 🟢 신규 |
| .claude/skills/ | 없음 | **7개 skill 파일** | 🟢 신규 |
| settings.json | 없음 | **SessionStart + flake8 + 토스트** | 🟢 신규 |
| mcp.json | 없음 | **Supabase + git** | 🟢 신규 |

---

## 통계 요약

| 태그 | 건수 |
|------|------|
| 동일 | 18 |
| 🟡 변경 (소규모) | 10 |
| 🔴 변경 (대규모) | 14 |
| 🟢 신규 | 24 |
| 🔴 삭제 | 1 (Agent 4) |
