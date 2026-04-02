# rendy .claude/ 구조 생성 계획

bon 프로젝트의 `.claude/` 구조 패턴을 rendy(LandingUp)의 architecture_spec.md 기준으로 매핑하여 생성.

---

## 생성할 파일 구조

```
c:\simhwa\rendy\
└── .claude/
    ├── settings.json                          ← 설정 (훅, 권한)
    ├── mcp.json                               ← Supabase + git MCP
    ├── agents/
    │   ├── agent-1-brand-extraction.md        ← Agent 1: 브랜드 수치 추출
    │   ├── agent-2-floorplan.md               ← Agent 2: 도면 분석 (전반부+후반부)
    │   ├── agent-3-placement.md               ← Agent 3: 배치 기획
    │   └── agent-5-report.md                  ← Agent 5: 리포트 생성
    └── skills/
        ├── brand_extraction.md                ← Agent 1 skill: PDF Regex + LLM 라벨링
        ├── floorplan_detection.md             ← Agent 2 전반부 skill: OpenCV + OCR + Vision
        ├── spatial_computation.md             ← Agent 2 후반부 skill: Dead Zone + 기준점 + NetworkX
        ├── object_selection.md                ← 오브젝트 선별 모듈 skill
        ├── placement_planning.md              ← Agent 3 skill: 배치 기획 + 코드 순회 루프
        ├── placement_verification.md          ← 검증 모듈 skill: 소방/시공 기준
        └── report.md                          ← Agent 5 skill: f-string 리포트 생성
```

---

## 매핑 근거 (bon → rendy)

| bon 파일 | rendy 대응 | 근거 |
|----------|-----------|------|
| `agents/agent-a-diagnosis.md` | `agents/agent-3-placement.md` | LLM이 핵심 판단하는 메인 Agent |
| `agents/agent-b-verification.md` | 검증 모듈 (skill만, agent 파일 없음) | 순수 코드 검증이므로 agent 불필요 |
| `agents/agent-c-personalization.md` | **없음** | rendy에 개인화 레이어 없음 |
| `skills/data_collection.md` | `skills/brand_extraction.md` + `skills/floorplan_detection.md` | architecture_spec 구조대로 분리 |
| `skills/diagnosis.md` | `skills/placement_planning.md` | 핵심 분석/판단 + 코드 순회 루프 |
| `skills/verification.md` | `skills/placement_verification.md` | 결과 검증 |
| `skills/sentiment_analysis.md` | Vision은 `floorplan_detection.md`에 포함 | 독립 파이프라인 아님, 분리 불필요 |
| `skills/personalization.md` | **없음** | rendy에 해당 없음 |
| `skills/report.md` | `skills/report.md` | 1:1 대응 |

## 미생성 항목 (skill 아님)

| 항목 | 이유 |
|------|------|
| `.glb 생성` | 프론트엔드 3D export 형식일 뿐, Claude 작업 규칙 아님 |
| `사용자 마킹 UI` | 프론트엔드 UI, skill 아님 |

---

## settings.json 구성

- **SessionStart**: `claude.md` 자동 로드 (rendy 경로)
- **PostToolUse**: flake8 (Edit|Write 시)
- **Stop**: Windows 토스트 알림 (LandingUp)
- architecture_spec.md와 충돌 없음 확인 ✅

## mcp.json 구성

- **Supabase**: furniture_standards 테이블 등 접근
- **git**: rendy 레포지토리
