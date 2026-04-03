import { useState, lazy, Suspense, Component, type ReactNode } from "react";
import { PlacementResult } from "../../api/placement";

const SceneViewer = lazy(() =>
  import("../viewer/SceneViewer").then(m => ({ default: m.SceneViewer }))
);

interface PlacementPageProps {
  result: PlacementResult | null;
  loading: boolean;
  error: string | null;
}

export function PlacementPage({ result, loading, error }: PlacementPageProps) {
  const [tab, setTab] = useState<"3d" | "report" | "log">("3d");

  if (loading) {
    return (
      <div style={styles.container}>
        <h2 style={styles.title}>배치 기획 진행 중...</h2>
        <p style={{ color: "#666", fontSize: 14 }}>
          Agent 3이 오브젝트 배치를 기획하고 있습니다. 잠시만 기다려주세요.
        </p>
        <div style={styles.spinner}>
          <style>{`@keyframes spin { to { transform: rotate(360deg) } }`}</style>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div style={styles.container}>
        <h2 style={styles.title}>배치 실패</h2>
        <p style={{ color: "#d32f2f", fontSize: 14 }}>{error}</p>
      </div>
    );
  }

  if (!result) return null;

  const v = result.verification;

  return (
    <div style={styles.container}>
      <h2 style={styles.title}>배치 결과</h2>

      {/* 검증 상태 배너 */}
      <div style={{
        padding: "12px 16px", borderRadius: 8, marginBottom: 16,
        background: v.passed ? "#e8f5e9" : "#fbe9e7",
        color: v.passed ? "#2e7d32" : "#c62828",
        fontWeight: 600, fontSize: 14,
      }}>
        검증: {v.passed ? "PASS" : "FAIL"} — {result.placed.length}개 배치, {result.dropped.length}개 드랍
        {v.blocking.length > 0 && ` / ${v.blocking.length}개 blocking`}
        {v.warning.length > 0 && ` / ${v.warning.length}개 warning`}
      </div>

      {/* 탭 */}
      <div style={{ display: "flex", gap: 0, borderBottom: "1px solid #e0e0e0", marginBottom: 16 }}>
        {(["3d", "report", "log"] as const).map(t => (
          <button key={t} onClick={() => setTab(t)} style={{
            padding: "10px 20px", border: "none", background: "none", cursor: "pointer",
            fontWeight: 600, fontSize: 14,
            color: tab === t ? "#1a1a1a" : "#aaa",
            borderBottom: tab === t ? "2px solid #1a1a1a" : "2px solid transparent",
          }}>
            {t === "3d" ? "3D 뷰어" : t === "report" ? "리포트" : "로그"}
          </button>
        ))}
      </div>

      {/* 3D 뷰어 — R3F 버전 충돌 시 fallback */}
      {tab === "3d" && (
        <>
          {/* [DEBUG] GLB 다운로드 버튼 — 외부 뷰어 테스트용 */}
          <button onClick={() => {
            const bin = atob(result.glb_base64);
            const bytes = new Uint8Array(bin.length);
            for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
            const blob = new Blob([bytes], { type: "model/gltf-binary" });
            const a = document.createElement("a");
            a.href = URL.createObjectURL(blob);
            a.download = "placement_debug.glb";
            a.click();
          }} style={{ marginBottom: 8, padding: "6px 12px", fontSize: 12, cursor: "pointer" }}>
            GLB 다운로드 (외부 뷰어 테스트용)
          </button>
          <ViewerErrorBoundary>
            <Suspense fallback={<div style={{ padding: 40, textAlign: "center", color: "#666" }}>3D 뷰어 로딩 중...</div>}>
              <SceneViewer glbBase64={result.glb_base64} />
            </Suspense>
          </ViewerErrorBoundary>
        </>
      )}

      {/* 리포트 */}
      {tab === "report" && (
        <pre style={styles.pre}>{result.report}</pre>
      )}

      {/* 로그 */}
      {tab === "log" && (
        <div>
          <h3 style={{ fontSize: 14, fontWeight: 700, marginBottom: 8 }}>배치 로그</h3>
          <pre style={styles.pre}>{result.log.join("\n")}</pre>

          {v.blocking.length > 0 && (
            <>
              <h3 style={{ fontSize: 14, fontWeight: 700, marginTop: 16, color: "#c62828" }}>Blocking</h3>
              {v.blocking.map((b, i) => (
                <div key={i} style={{ fontSize: 13, color: "#c62828", padding: "4px 0" }}>
                  {b.object_type}: {b.detail}
                </div>
              ))}
            </>
          )}

          {v.warning.length > 0 && (
            <>
              <h3 style={{ fontSize: 14, fontWeight: 700, marginTop: 16, color: "#e65100" }}>Warnings</h3>
              {v.warning.map((w, i) => (
                <div key={i} style={{ fontSize: 13, color: "#e65100", padding: "4px 0" }}>
                  {w.object_type}: {w.detail}
                </div>
              ))}
            </>
          )}

          {result.dropped.length > 0 && (
            <>
              <h3 style={{ fontSize: 14, fontWeight: 700, marginTop: 16, color: "#555" }}>Dropped</h3>
              {result.dropped.map((d, i) => (
                <div key={i} style={{ fontSize: 13, color: "#555", padding: "4px 0" }}>
                  {String((d as Record<string,unknown>).object_type)}: {String((d as Record<string,unknown>).reason)}
                </div>
              ))}
            </>
          )}
        </div>
      )}
    </div>
  );
}

class ViewerErrorBoundary extends Component<{children: ReactNode}, {error: string | null}> {
  state = { error: null as string | null };
  static getDerivedStateFromError(e: Error) { return { error: e.message }; }
  render() {
    if (this.state.error) {
      return (
        <div style={{ padding: 40, textAlign: "center", color: "#c62828", background: "#fbe9e7", borderRadius: 8 }}>
          <p style={{ fontWeight: 700 }}>3D 뷰어 로드 실패</p>
          <p style={{ fontSize: 13 }}>{this.state.error}</p>
          <p style={{ fontSize: 12, color: "#666" }}>리포트/로그 탭에서 배치 결과를 확인하세요.</p>
        </div>
      );
    }
    return this.props.children;
  }
}

const styles: Record<string, React.CSSProperties> = {
  container: { maxWidth: 900, margin: "40px auto", padding: "0 24px", fontFamily: "sans-serif" },
  title:     { fontSize: 22, fontWeight: 700, marginBottom: 16 },
  pre:       { background: "#f5f5f5", padding: 16, borderRadius: 8, fontSize: 12,
               lineHeight: 1.6, overflowX: "auto", whiteSpace: "pre-wrap" },
  spinner:   { width: 40, height: 40, border: "4px solid #e0e0e0", borderTopColor: "#1a1a1a",
               borderRadius: "50%", animation: "spin 1s linear infinite", margin: "40px auto" },
};
