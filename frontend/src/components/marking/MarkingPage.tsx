/**
 * MarkingPage — 순수 View 계층.
 * 상태/이벤트는 useMarkingCanvas, 스케일 앵커는 ScaleAnchorPopup에서 주입.
 */
import { useMemo, useState, useCallback } from "react";
import { ParsedDrawings, ParsedFloorPlan, buildSpaceData } from "../../api/detect";
import { useMarkingCanvas, COLORS, type AddMode } from "./useMarkingCanvas";
import { ScaleAnchorPopup } from "./ScaleAnchorManager";

interface MarkingPageProps {
  drawings: ParsedDrawings;
  floorFile: File;
  onComplete: (spaceData: Record<string, unknown>, scale: number, editedDrawings: ParsedDrawings) => void;
}

export function MarkingPage({ drawings: initialDrawings, floorFile, onComplete }: MarkingPageProps) {
  // ── 상태 ──────────────────────────────────────────────────────────────────
  const [fp, setFp] = useState<ParsedFloorPlan>(() => structuredClone(initialDrawings.floor_plan));
  const [scale, setScale] = useState(initialDrawings.floor_plan.scale_mm_per_px);
  const [scaleInput, setScaleInput] = useState(String(Math.round(scale * 10) / 10));
  const [widthMm, setWidthMm] = useState(initialDrawings.floor_plan.detected_width_mm ?? 0);
  const [heightMm, setHeightMm] = useState(initialDrawings.floor_plan.detected_height_mm ?? 0);
  const [loading, setLoading] = useState(false);
  const [addMode, setAddMode] = useState<AddMode>(null);
  const [roomDrawPts, setRoomDrawPts] = useState<[number, number][]>([]);
  const [anchorPts, setAnchorPts] = useState<[number, number][]>([]);
  const [anchorLine, setAnchorLine] = useState<{ start: [number, number]; end: [number, number]; mm: number } | null>(null);
  const [anchorInput, setAnchorInput] = useState(false);
  const [zoom, setZoom] = useState(100); // %

  const zoomIn = useCallback(() => setZoom(z => Math.min(z + 25, 300)), []);
  const zoomOut = useCallback(() => setZoom(z => Math.max(z - 25, 50)), []);
  const zoomReset = useCallback(() => setZoom(100), []);

  // ── Hooks ─────────────────────────────────────────────────────────────────
  const {
    canvasRef, imgRef, cursor,
    handleMouseDown, handleMouseMove, handleMouseUp, handleContextMenu, handleImgLoad,
  } = useMarkingCanvas({
    fp, setFp, addMode, setAddMode,
    dxfViewport: initialDrawings.dxf_viewport,
    anchorPts, setAnchorPts, anchorLine, setAnchorLine, setAnchorInput,
    roomDrawPts, setRoomDrawPts,
  });

  const imgUrl = useMemo(() => {
    const preview = initialDrawings.preview_image_base64;
    if (preview) return `data:image/png;base64,${preview}`;
    return URL.createObjectURL(floorFile);
  }, [floorFile, initialDrawings.preview_image_base64]);

  const currentDrawings = useMemo<ParsedDrawings>(() => ({
    floor_plan: fp, section: initialDrawings.section,
  }), [fp, initialDrawings.section]);

  // ── 확정 ──────────────────────────────────────────────────────────────────
  async function handleConfirm() {
    setLoading(true);
    try {
      const userDims = (widthMm > 0 && heightMm > 0) ? { width_mm: widthMm, height_mm: heightMm } : undefined;
      const sd = await buildSpaceData(currentDrawings, scale, undefined, userDims);
      // 편집된 drawings를 App에 전달 (ConfirmPage에서 polygon clipping에 필요)
      const editedDrawings: ParsedDrawings = {
        ...currentDrawings,
        preview_image_base64: initialDrawings.preview_image_base64,
        dxf_viewport: initialDrawings.dxf_viewport,
      };
      onComplete(sd, scale, editedDrawings);
    } finally { setLoading(false); }
  }

  function recalcScale(w: number, h: number) {
    const xs = fp.floor_polygon_px.map(p => p[0]);
    const ys = fp.floor_polygon_px.map(p => p[1]);
    const pxW = Math.max(...xs) - Math.min(...xs);
    const pxH = Math.max(...ys) - Math.min(...ys);
    const scales: number[] = [];
    if (w > 0 && pxW > 0) scales.push(w / pxW);
    if (h > 0 && pxH > 0) scales.push(h / pxH);
    if (scales.length > 0) {
      const avg = scales.reduce((a, b) => a + b) / scales.length;
      setScale(avg);
      setScaleInput(String(Math.round(avg * 100) / 100));
    }
  }

  // ── JSX ───────────────────────────────────────────────────────────────────
  return (
    <div style={styles.container}>
      <h2 style={styles.title}>감지 결과 확인 / 수정</h2>
      <p style={{ fontSize: 13, color: "#666", marginBottom: 12 }}>
        꼭짓점 드래그로 바닥 윤곽 수정. 마커 드래그로 위치 이동. 우클릭으로 삭제.
      </p>

      {/* 범례 + 추가 버튼 */}
      <div style={styles.toolbar}>
        {Object.entries(COLORS).filter(([k]) => !["vertex", "vertexHover", "inaccessible", "wall"].includes(k)).map(([k, c]) => (
          <span key={k} style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 12 }}>
            <span style={{ width: 12, height: 12, background: c, display: "inline-block", borderRadius: 2 }} />
            {k === "panel" ? "electrical panel" : k}
          </span>
        ))}
        <span style={{ flex: 1 }} />
        {(["entrance", "sprinkler", "hydrant", "panel", "inaccessible", "scale_anchor"] as const).map(mode => (
          <button key={mode} style={{
            ...styles.addBtn,
            background: addMode === mode ? (mode === "scale_anchor" ? "#e91e63" : "#1a1a1a") : "#fff",
            color: addMode === mode ? "#fff" : "#333",
            borderColor: mode === "scale_anchor" ? "#e91e63" : "#ccc",
          }} onClick={() => { setAddMode(addMode === mode ? null : mode); setRoomDrawPts([]); setAnchorPts([]); }}>
            {mode === "scale_anchor" ? (anchorPts.length === 1 ? "스케일 앵커 (1/2)" : "스케일 앵커")
              : mode === "panel" ? "+ electrical panel" : `+ ${mode}`}
            {mode === "inaccessible" && roomDrawPts.length > 0 ? ` (${roomDrawPts.length}/4)` : ""}
          </button>
        ))}
      </div>

      {/* 스케일 앵커 팝업 */}
      {anchorInput && anchorLine && (
        <ScaleAnchorPopup
          anchorLine={anchorLine} fp={fp}
          setScale={setScale} setScaleInput={setScaleInput}
          setWidthMm={setWidthMm} setHeightMm={setHeightMm}
          setAnchorLine={setAnchorLine} setAnchorInput={setAnchorInput}
          styles={styles}
        />
      )}

      {/* 확대/축소 */}
      <div style={{ display: "flex", gap: 6, marginBottom: 8, alignItems: "center" }}>
        <button onClick={zoomOut} style={styles.zoomBtn} title="축소">−</button>
        <span style={{ fontSize: 12, minWidth: 40, textAlign: "center" }}>{zoom}%</span>
        <button onClick={zoomIn} style={styles.zoomBtn} title="확대">+</button>
        <button onClick={zoomReset} style={{ ...styles.zoomBtn, fontSize: 11, padding: "2px 8px" }}>초기화</button>
      </div>

      {/* 도면 + canvas */}
      <div style={{ position: "relative", overflow: "auto", border: "1px solid #e0e0e0", borderRadius: 8, maxHeight: 700 }}>
        <div style={{ width: `${zoom}%`, position: "relative" }}>
          <img ref={imgRef} src={imgUrl} alt="floor plan" onLoad={handleImgLoad} style={{ width: "100%", display: "block" }} />
          <canvas ref={canvasRef}
            onMouseDown={handleMouseDown} onMouseMove={handleMouseMove}
            onMouseUp={handleMouseUp} onMouseLeave={handleMouseUp}
            onContextMenu={handleContextMenu}
            style={{ position: "absolute", top: 0, left: 0, width: "100%", height: "100%", cursor }}
          />
        </div>
      </div>

      {/* scale 입력 */}
      <div style={styles.scaleRow}>
        <span style={{ fontSize: 14 }}>
          Scale {fp.scale_confirmed ? `(Vision 추정: ${Math.round(scale * 10) / 10}mm/px)` : "미확인 — 실제 치수 직접 입력 권장"}
        </span>
        <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
          <label style={{ fontSize: 13 }}>가로 (mm)</label>
          <input type="number" style={styles.input} placeholder="예: 12000" value={widthMm || ""}
            onChange={e => { const w = parseFloat(e.target.value) || 0; setWidthMm(w); recalcScale(w, heightMm); }} />
          <label style={{ fontSize: 13 }}>세로 (mm)</label>
          <input type="number" style={styles.input} placeholder="예: 8000" value={heightMm || ""}
            onChange={e => { const h = parseFloat(e.target.value) || 0; setHeightMm(h); recalcScale(widthMm, h); }} />
          <span style={{ fontSize: 13, color: "#555" }}>{scaleInput} mm/px</span>
        </div>
      </div>

      {/* 편집 요약 */}
      <div style={{ fontSize: 12, color: "#888", marginTop: 8 }}>
        polygon {fp.floor_polygon_px.length}점 ·
        entrance {(fp.entrances?.length || 0) + (fp.entrance && !fp.entrances?.length ? 1 : 0)}개 ·
        S {fp.sprinklers.length} · H {fp.fire_hydrant.length} · P {fp.electrical_panel.length} ·
        배치불가 {fp.inaccessible_rooms.length}개
        {anchorLine && anchorLine.mm > 0 && ` · 스케일 앵커: ${anchorLine.mm}mm`}
      </div>

      <button style={styles.button} onClick={handleConfirm} disabled={loading}>
        {loading ? "공간 연산 중…" : "확정 → 다음 단계"}
      </button>
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  container: { maxWidth: 900, margin: "40px auto", padding: "0 24px", fontFamily: "sans-serif" },
  title: { fontSize: 22, fontWeight: 700, marginBottom: 8 },
  toolbar: { display: "flex", flexWrap: "wrap", gap: 12, marginBottom: 12, alignItems: "center" },
  addBtn: { fontSize: 11, padding: "4px 10px", border: "1px solid #ccc", borderRadius: 4, cursor: "pointer" },
  scaleRow: { marginTop: 16, display: "flex", flexDirection: "column", gap: 8, padding: 16, background: "#f5f5f5", borderRadius: 8 },
  input: { padding: "6px 10px", border: "1px solid #ccc", borderRadius: 4, width: 120 },
  zoomBtn: { width: 28, height: 28, border: "1px solid #ccc", borderRadius: 4, background: "#fff", fontSize: 16, cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center" },
  button: { marginTop: 20, width: "100%", padding: "14px 0", background: "#1a1a1a", color: "#fff", border: "none", borderRadius: 8, fontSize: 16, fontWeight: 600, cursor: "pointer" },
  anchorPopup: { marginBottom: 12, padding: 16, background: "#fce4ec", borderRadius: 8, display: "flex", flexDirection: "column" as const, gap: 8 },
};
