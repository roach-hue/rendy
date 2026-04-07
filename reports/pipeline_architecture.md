# Rendy 파이프라인 아키텍처

> 최종 갱신: 2026-04-07

---

## 전체 파이프라인 흐름

```mermaid
flowchart TD
    A[도면 + 브랜드 메뉴얼 업로드] --> B[Agent 1: 브랜드 추출]
    A --> C[Agent 2 전반부: 도면 감지]
    B --> D[브랜드 확인 UI]
    C --> E[사용자 마킹 UI]
    D --> F[Agent 2 후반부: 공간 분석]
    E --> F
    F --> G[1단계 확인 UI]
    G --> H[오브젝트 선별 모듈]
    H --> I[Agent 3: 배치 기획]
    I --> J[Placement Engine: 코드 순회 루프]
    J --> K{배치 성공?}
    K -->|성공| L[Verification: 검증]
    K -->|실패| M{cascade?}
    M -->|cascade| N[Choke Point 피드백 → Agent 3 재호출]
    M -->|물리 한계| O[Graceful Degradation: drop]
    N -->|최대 2회| I
    N -->|소진| P[Deterministic Fallback]
    P --> L
    O --> L
    L --> Q[GLB 생성]
    Q --> R[Agent 5: 리포트]
    R --> S[3D 뷰어 + 동선 시각화]

    style A fill:#e3f2fd
    style I fill:#fff3e0
    style J fill:#e8f5e9
    style L fill:#fce4ec
    style S fill:#f3e5f5
```

---

## Agent별 역할과 I/O

```mermaid
flowchart LR
    subgraph Agent1["Agent 1 — 브랜드 추출"]
        A1_IN["PDF 바이트"] --> A1_PROC["Regex 수치 추출\n+ LLM 라벨링"]
        A1_PROC --> A1_OUT["brand_data\nclearspace_mm\nprohibited_material\nobject_pair_rules"]
    end

    subgraph Agent2F["Agent 2 전반부 — 도면 감지"]
        A2F_IN["도면 파일"] --> A2F_PROC["파서 어댑터\nDXF/PDF/Image\n+ Claude Vision"]
        A2F_PROC --> A2F_OUT["ParsedDrawings\nfloor_polygon_px\nentrances\nsprinklers\nfire_hydrant\nelectrical_panel"]
    end

    subgraph Agent2B["Agent 2 후반부 — 공간 분석 (코드)"]
        A2B_IN["ParsedDrawings\n+ scale_mm_per_px"] --> A2B_PROC["6개 모듈 순차 실행"]
        A2B_PROC --> A2B_OUT["space_data dict\n2500+ slots\nwalk_mm\nzone_label\nspine_rank\nMain Spine"]
    end

    subgraph Agent3["Agent 3 — 배치 기획 (LLM)"]
        A3_IN["공간 요약 50줄\n+ Spine 구조\n+ eligible 기물\n+ 브랜드 제약"] --> A3_PROC["Claude Sonnet 4.5\nP1~P4 규칙\nCircuit Breaker 3회"]
        A3_PROC --> A3_OUT["Placement[]\nzone_label\ndirection\npriority\nalignment\nplaced_because"]
    end

    subgraph Agent5["Agent 5 — 리포트 (템플릿)"]
        A5_IN["배치 결과\n+ 검증 결과"] --> A5_PROC["f-string 템플릿\n기계 조립"]
        A5_PROC --> A5_OUT["마크다운 리포트"]
    end

    style Agent1 fill:#e3f2fd
    style Agent2F fill:#e8f5e9
    style Agent2B fill:#e8f5e9
    style Agent3 fill:#fff3e0
    style Agent5 fill:#f3e5f5
```

---

## Agent 2 후반부 — 6개 모듈 상세

```mermaid
flowchart TD
    INPUT["ParsedDrawings + scale"] --> S1

    S1["1. Dead Zone Generator\n설비 buffer + inaccessible 차감"] --> S2
    S2["2. Slot Generator\n외벽 edge slots + 내부 격자 slots"] --> S3
    S3["3. Corridor Graph\nNetworkX 500mm 격자 + Choke Point"] --> S4
    S4["4. Walk MM Calculator\nDijkstra walk_mm + zone_label\n+ Main Spine 직각 경로"] --> S5
    S5["5. Semantic Tags\ncorner / wall_adjacent / center_area"] --> S6
    S6["6. Spine Proximity\nspine_rank: adjacent / nearby / far"] --> OUTPUT

    OUTPUT["space_data 확정\n+ _agent3_summary"]

    style S4 fill:#fff3e0
    style S6 fill:#fff3e0
```

---

## Placement Engine — 배치 순회 루프

```mermaid
flowchart TD
    START["Agent 3 Placement 리스트\n(priority 순)"] --> LOOP

    LOOP["기물 1개 선택"] --> ZONE["zone_label 일치 슬롯 필터"]
    ZONE --> SORT["spine_rank 정렬\nwall_facing→far 우선\ninward→adjacent 우선"]
    SORT --> SLOT["슬롯 1개 시도"]

    SLOT --> C1{"floor 내부?\n(95%)"}
    C1 -->|X| NEXT_SLOT
    C1 -->|O| C2{"static_cache\n충돌?"}
    C2 -->|O| NEXT_SLOT
    C2 -->|X| C3{"기배치 오브젝트\n충돌?"}
    C3 -->|O| NEXT_SLOT
    C3 -->|X| C4{"통로 450mm\n확보?"}
    C4 -->|X| NEXT_SLOT
    C4 -->|O| C5{"관계 제약\nclearspace?"}
    C5 -->|위반| NEXT_SLOT
    C5 -->|통과| C6{"NetworkX\n통로 연결성?"}
    C6 -->|차단| NEXT_SLOT
    C6 -->|유지| C7{"Choke Point\n900mm?"}
    C7 -->|병목| NEXT_SLOT
    C7 -->|통과| C8{"IQI 밀도\n25%?"}
    C8 -->|초과| DROP["밀도 초과 drop"]
    C8 -->|이내| PLACED["배치 확정"]

    NEXT_SLOT["다음 슬롯"] --> SLOT
    PLACED --> NEXT_OBJ["다음 기물"]
    NEXT_OBJ --> LOOP

    style PLACED fill:#c8e6c9
    style DROP fill:#ffcdd2
```

---

## 동선 시스템

```mermaid
flowchart TD
    subgraph MainSpine["주동선 (Main Spine) — 핑크"]
        MS1["입구 위치 + 바닥 형태"] --> MS2["최원 벽면 중앙 식별"]
        MS2 --> MS3["직각 경유점 산출\nㄱ자 / 직진"]
        MS3 --> MS4["Dijkstra 그리드 연결"]
        MS4 --> MS5["LineString 생성"]
    end

    subgraph SubPath["부동선 (Sub-path) — 초록"]
        SP1["배치 완료된 기물 좌표"] --> SP2{"Spine에서 2m+\n떨어진 기물?"}
        SP2 -->|있음| SP3["기물 경유점\nnearest-neighbor 순"]
        SP2 -->|없음| SP4["Spine 반대편\n외곽 3점 fallback"]
        SP3 --> SP5["Spine 종점 →\n경유점 → 입구\nDijkstra 연결"]
        SP4 --> SP5
    end

    subgraph Render["3D 렌더링"]
        R1["Main Spine → CatmullRom\n800mm 리본 메시 (핑크)"]
        R2["Sub-path → CatmullRom\n라인 (초록)"]
        R3["입구 → 바닥 데칼\n링 + 십자 (초록)"]
        R4["Zone Disc → 원형 메시\nwalk_mm 그라데이션"]
    end

    MS5 --> R1
    SP5 --> R2

    style MainSpine fill:#fce4ec
    style SubPath fill:#e8f5e9
```

---

## 복수 입구 처리

```mermaid
flowchart TD
    E1["입구 1: MAIN_DOOR\n(상단)"] --> WM["walk_mm =\nmin(전체 입구 거리)"]
    E2["입구 2: EMERGENCY_EXIT\n(우측)"] --> WM

    WM --> ZL["zone_label =\nMAIN 기준 단방향\n(VMD 위계 유지)"]

    E1 --> SPINE["Main Spine\nMAIN → deep wall → EXIT\n관통 동선"]
    E2 --> SPINE

    E1 --> BUF["entrance_buffer\n전체 입구 병합\n(unary_union)"]
    E2 --> BUF

    style E1 fill:#c8e6c9
    style E2 fill:#bbdefb
```

---

## 실패 처리 계층

```mermaid
flowchart TD
    FAIL["배치 실패"] --> SOLO{"단독 배치\n테스트"}

    SOLO -->|단독도 실패| PHYS["물리적 한계\n→ Graceful Degradation\n(drop + 사유)"]
    SOLO -->|단독은 성공| CASCADE["cascade failure\n→ Choke Point 피드백 추출"]

    CASCADE --> RETRY{"재호출\n횟수?"}
    RETRY -->|≤ 2회| RECALL["Agent 3 재호출\nf-string 피드백 전달"]
    RETRY -->|> 2회| DETER["Deterministic Fallback\nzone 무시 전체 순회\nsource: fallback"]

    RECALL --> ENGINE["Placement Engine 재실행"]
    DETER --> ENGINE

    style PHYS fill:#ffcdd2
    style DETER fill:#fff9c4
    style RECALL fill:#fff3e0
```

---

## 세션 영속화

```mermaid
flowchart LR
    PIPE["파이프라인 완료"] --> LOCAL["로컬 캐시\ncache/placement/\n{hash}.json"]
    PIPE --> DB["Supabase\nsession_cache\nsession_key + JSONB"]

    REQ["배치 요청"] --> CHECK1{"로컬 캐시?"}
    CHECK1 -->|히트| RES["응답 (0.1초)"]
    CHECK1 -->|미스| CHECK2{"DB 캐시?"}
    CHECK2 -->|히트| RESTORE["로컬 복원 + 응답 (1.5초)"]
    CHECK2 -->|미스| FULL["전체 파이프라인 (60~120초)"]

    style LOCAL fill:#e8f5e9
    style DB fill:#e3f2fd
    style FULL fill:#ffcdd2
```

---

## 기술 스택

| 계층 | 기술 |
|------|------|
| Frontend | React + Vite + TypeScript + Three.js (R3F + drei) |
| Backend | FastAPI + Python 3.12 |
| AI | Claude Sonnet 4.5 (Agent 1, 2 전반부, 3) |
| 기하학 | Shapely (충돌/buffer) + NetworkX (경로/통로) |
| 3D 출력 | trimesh (GLB) + InstancedMesh (프론트) |
| DB | Supabase (furniture_standards + session_cache) |
| 파서 | ezdxf (DXF) + pdfplumber (PDF) + OpenCV + Vision (Image) |

---

## 파일 구조 (37 Python 파일)

```
backend/app/
├── agents/
│   ├── agent1_brand.py          # Agent 1: 브랜드 추출
│   ├── agent2_back.py           # Agent 2 후반부: 오케스트레이터
│   ├── agent2_summary.py        # Agent 3용 요약 생성
│   ├── agent3_placement.py      # Agent 3: LLM 배치 기획
│   ├── corridor_graph.py        # NetworkX 격자 + Choke Point
│   ├── dead_zone_generator.py   # Dead Zone 생성
│   ├── slot_generator.py        # 슬롯 생성 (edge + interior)
│   └── walk_mm_calculator.py    # walk_mm + Main Spine
├── api/
│   ├── routes.py                # FastAPI 라우터
│   ├── pipeline.py              # 파이프라인 오케스트레이터
│   ├── cache_service.py         # 로컬 캐시
│   ├── session_store.py         # Supabase 세션 영속화
│   ├── file_converter.py        # DXF→PNG 프리뷰
│   ├── object_crud.py           # furniture_standards CRUD
│   └── serializer.py            # Shapely → JSON
├── modules/
│   ├── placement_engine.py      # 배치 엔진 (코드 순회)
│   ├── calculate_position.py    # 좌표 계산
│   ├── verification.py          # 배치 검증
│   ├── report_generator.py      # Agent 5 리포트
│   ├── glb_exporter.py          # GLB 생성
│   ├── object_selection.py      # IQI + 기물 선별
│   ├── failure_handler.py       # 실패 처리 + fallback
│   ├── failure_classifier.py    # 실패 분류
│   ├── fallback_placement.py    # Deterministic Fallback
│   └── geometry_cache.py        # InstancedMesh geometry_id
├── parsers/
│   ├── base.py                  # FloorPlanParser 추상 클래스
│   ├── dxf_parser.py            # DXF 파서 (ezdxf)
│   ├── dwg_parser.py            # DWG 파서 (ODA 경유)
│   ├── image_parser.py          # Image 파서 (Vision)
│   ├── pdf_parser.py            # PDF 파서
│   └── factory.py               # 파서 팩토리
└── schemas/
    ├── drawings.py              # ParsedDrawings
    ├── placement.py             # Placement
    ├── space_data.py            # space_data 유틸
    ├── verification.py          # SummaryReport
    └── brand.py                 # 브랜드 스키마
```
