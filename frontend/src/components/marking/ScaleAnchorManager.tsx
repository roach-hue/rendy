/**
 * 스케일 앵커 팝업 + API 호출.
 */
import type { ParsedFloorPlan } from "../../api/detect";

interface ScaleAnchorProps {
  anchorLine: { start: [number, number]; end: [number, number]; mm: number };
  fp: ParsedFloorPlan;
  setScale: (s: number) => void;
  setScaleInput: (s: string) => void;
  setWidthMm: (w: number) => void;
  setHeightMm: (h: number) => void;
  setAnchorLine: (v: { start: [number, number]; end: [number, number]; mm: number } | null) => void;
  setAnchorInput: (v: boolean) => void;
  styles: Record<string, React.CSSProperties>;
}

export function ScaleAnchorPopup({
  anchorLine, fp, setScale, setScaleInput, setWidthMm, setHeightMm, setAnchorLine, setAnchorInput, styles,
}: ScaleAnchorProps) {
  async function handleConfirm(mmValue: number) {
    if (mmValue <= 0) return;
    setAnchorInput(false);
    const line = { ...anchorLine, mm: mmValue };
    setAnchorLine(line);

    try {
      const res = await fetch("/api/scale-correct", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ actual_length_mm: mmValue, ref_start_px: line.start, ref_end_px: line.end }),
      });
      if (!res.ok) throw new Error(`scale-correct 실패: ${res.status}`);
      const data = await res.json();
      const newScale = data.scale_mm_per_px as number;
      setScale(newScale);
      setScaleInput(String(Math.round(newScale * 100) / 100));
      const xs = fp.floor_polygon_px.map(p => p[0]);
      const ys = fp.floor_polygon_px.map(p => p[1]);
      setWidthMm(Math.round((Math.max(...xs) - Math.min(...xs)) * newScale));
      setHeightMm(Math.round((Math.max(...ys) - Math.min(...ys)) * newScale));
    } catch (e) {
      console.error("[ScaleAnchor] failed:", e);
    }
  }

  const pxLen = Math.round(Math.hypot(
    anchorLine.end[0] - anchorLine.start[0],
    anchorLine.end[1] - anchorLine.start[1],
  ));

  return (
    <div style={styles.anchorPopup}>
      <span style={{ fontSize: 13, fontWeight: 600 }}>
        선분 길이: {pxLen}px — 실제 길이(mm)를 입력하세요
      </span>
      <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
        <input
          type="number" placeholder="예: 2000" autoFocus style={styles.input}
          onKeyDown={e => {
            if (e.key === "Enter") {
              const v = parseFloat((e.target as HTMLInputElement).value) || 0;
              if (v > 0) handleConfirm(v);
            }
          }}
        />
        <button
          style={{ ...styles.addBtn, background: "#e91e63", color: "#fff", borderColor: "#e91e63" }}
          onClick={() => {
            const input = document.querySelector<HTMLInputElement>("[placeholder='예: 2000']");
            const v = parseFloat(input?.value ?? "") || 0;
            if (v > 0) handleConfirm(v);
          }}
        >적용</button>
        <button style={styles.addBtn} onClick={() => { setAnchorInput(false); setAnchorLine(null); }}>취소</button>
      </div>
    </div>
  );
}
