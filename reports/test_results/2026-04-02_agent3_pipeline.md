# Agent 3 + 전체 파이프라인 + FE-4

**날짜**: 2026-04-02
**대상**: Agent 3 LLM 배치 기획, 파이프라인 통합 API, 3D 뷰어

## 구현 완료 (단위 테스트 대상 아님 — 통합 테스트 필요)

| # | 항목 | 파일 | 상태 |
|---|------|------|------|
| 1 | Agent 3 LLM 배치 기획 | `backend/app/agents/agent3_placement.py` | 구현 완료, LLM 호출 필요 |
| 2 | 전체 파이프라인 API | `backend/app/api/routes.py` `/api/placement` | 구현 완료 |
| 3 | 3D 뷰어 (R3F) | `frontend/src/components/viewer/SceneViewer.tsx` | 구현 완료 |
| 4 | 배치 결과 페이지 | `frontend/src/components/placement/PlacementPage.tsx` | 구현 완료 |
| 5 | 배치 API 클라이언트 | `frontend/src/api/placement.ts` | 구현 완료 |
| 6 | App.tsx 4단계 연결 | `frontend/src/App.tsx` | 구현 완료 |

## 통합 테스트 방법

1. 백엔드 기동: `cd backend && uvicorn main:app --port 8000 --reload`
2. 프론트 기동: `cd frontend && npm run dev`
3. 브라우저: `http://localhost:5173`
4. 도면 + 브랜드 메뉴얼 업로드 → 감지 확인 → 검토 → 확정
5. 4단계에서 Agent 3 LLM 호출 → 배치 결과 3D 뷰어 + 리포트 확인

## 의존성 추가

- `@react-three/fiber`, `@react-three/drei` (npm --legacy-peer-deps)
- `trimesh`, `scipy` (backend requirements.txt)
