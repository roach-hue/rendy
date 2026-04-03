import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ParsedDrawings, ParsedFloorPlan, DetectedPoint, buildSpaceData } from "../../api/detect";

interface MarkingPageProps {
  drawings: ParsedDrawings;
  floorFile: File;
  onComplete: (spaceData: Record<string, unknown>, scale: number) => void;
}

type DragTarget =
  | { type: "vertex"; index: number }
  | { type: "entrance" }
  | { type: "equipment"; kind: "sprinklers" | "fire_hydrant" | "electrical_panel"; index: number }
  | { type: "room_vertex"; roomIndex: number; vertexIndex: number }
  | null;

type AddMode = "entrance" | "sprinkler" | "hydrant" | "panel" | "inaccessible" | "scale_anchor" | null;

const HIT_RADIUS = 14;
const VERTEX_RADIUS = 6;

const COLORS: Record<string, string> = {
  floor:        "#2196f3",
  vertex:       "#1565c0",
  vertexHover:  "#e91e63",
  entrance:     "#4caf50",
  sprinkler:    "#ff9800",
  hydrant:      "#f44336",
  panel:        "#9c27b0",
  wall:         "#795548",
  inaccessible: "rgba(0,0,0,0.25)",
};

export function MarkingPage({ drawings: initialDrawings, floorFile, onComplete }: MarkingPageProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const imgRef = useRef<HTMLImageElement>(null);
  const [fp, setFp] = useState<ParsedFloorPlan>(() => structuredClone(initialDrawings.floor_plan));
  const [scale, setScale] = useState(initialDrawings.floor_plan.scale_mm_per_px);
  const [scaleInput, setScaleInput] = useState(String(Math.round(scale * 10) / 10));
  const [widthMm, setWidthMm] = useState(initialDrawings.floor_plan.detected_width_mm ?? 0);
  const [heightMm, setHeightMm] = useState(initialDrawings.floor_plan.detected_height_mm ?? 0);
  const [loading, setLoading] = useState(false);
  const [dragTarget, setDragTarget] = useState<DragTarget>(null);
  const [addMode, setAddMode] = useState<AddMode>(null);
  const [hoverVertex, setHoverVertex] = useState<number | null>(null);
  const [roomDrawPts, setRoomDrawPts] = useState<[number, number][]>([]);
  // 스케일 앵커: 2점 선분 + 실제 mm 입력
  const [anchorPts, setAnchorPts] = useState<[number, number][]>([]);
  const [anchorLine, setAnchorLine] = useState<{ start: [number, number]; end: [number, number]; mm: number } | null>(null);
  const [anchorInput, setAnchorInput] = useState(false); // mm 입력 팝업

  // PDF/DXF: preview_image_base64 사용, 이미지: blob URL
  const imgUrl = useMemo(() => {
    const preview = initialDrawings.preview_image_base64;
    if (preview) return `data:image/png;base64,${preview}`;
    return URL.createObjectURL(floorFile);
  }, [floorFile, initialDrawings.preview_image_base64]);

  // 현재 drawings 객체 (fp 변경 반영)
  const currentDrawings = useMemo<ParsedDrawings>(() => ({
    floor_plan: fp,
    section: initialDrawings.section,
  }), [fp, initialDrawings.section]);

  // ── canvas 좌표 변환 ──────────────────────────────────────────────────────
  function canvasXY(e: React.MouseEvent<HTMLCanvasElement>): [number, number] {
    const canvas = canvasRef.current!;
    const rect = canvas.getBoundingClientRect();
    const scaleX = canvas.width / rect.width;
    const scaleY = canvas.height / rect.height;
    return [(e.clientX - rect.left) * scaleX, (e.clientY - rect.top) * scaleY];
  }

  function dist(ax: number, ay: number, bx: number, by: number) {
    return Math.hypot(ax - bx, ay - by);
  }

  // ── 그리기 ────────────────────────────────────────────────────────────────
  const redraw = useCallback(() => {
    const canvas = canvasRef.current;
    const img = imgRef.current;
    if (!canvas || !img) return;
    canvas.width = img.naturalWidth;
    canvas.height = img.naturalHeight;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    // polygon
    if (fp.floor_polygon_px.length > 2) {
      ctx.beginPath();
      ctx.moveTo(...fp.floor_polygon_px[0]);
      fp.floor_polygon_px.slice(1).forEach(p => ctx.lineTo(...p));
      ctx.closePath();
      ctx.strokeStyle = COLORS.floor;
      ctx.lineWidth = 2;
      ctx.stroke();
      ctx.fillStyle = COLORS.floor + "10";
      ctx.fill();

      // 꼭짓점 핸들
      fp.floor_polygon_px.forEach(([x, y], i) => {
        ctx.beginPath();
        ctx.arc(x, y, VERTEX_RADIUS, 0, Math.PI * 2);
        ctx.fillStyle = i === hoverVertex ? COLORS.vertexHover : COLORS.vertex;
        ctx.fill();
        ctx.strokeStyle = "#fff";
        ctx.lineWidth = 2;
        ctx.stroke();
      });
    }

    // inaccessible rooms + 꼭짓점 핸들
    fp.inaccessible_rooms.forEach(r => {
      ctx.beginPath();
      ctx.moveTo(...r.polygon_px[0]);
      r.polygon_px.slice(1).forEach(p => ctx.lineTo(...p));
      ctx.closePath();
      ctx.fillStyle = COLORS.inaccessible;
      ctx.fill();
      ctx.strokeStyle = "#000";
      ctx.lineWidth = 1;
      ctx.stroke();
      // 꼭짓점 핸들 (빨간 작은 점)
      r.polygon_px.forEach(([x, y]) => {
        ctx.beginPath();
        ctx.arc(x, y, 4, 0, Math.PI * 2);
        ctx.fillStyle = "#d32f2f";
        ctx.fill();
      });
    });

    // inaccessible 그리기 중간 점 표시
    if (roomDrawPts.length > 0) {
      ctx.beginPath();
      ctx.moveTo(...roomDrawPts[0]);
      roomDrawPts.slice(1).forEach(p => ctx.lineTo(...p));
      ctx.strokeStyle = "#d32f2f";
      ctx.lineWidth = 2;
      ctx.setLineDash([6, 4]);
      ctx.stroke();
      ctx.setLineDash([]);
      roomDrawPts.forEach(([x, y]) => {
        ctx.beginPath();
        ctx.arc(x, y, 5, 0, Math.PI * 2);
        ctx.fillStyle = "#d32f2f";
        ctx.fill();
      });
    }

    // inner walls
    fp.inner_walls.forEach(w => {
      ctx.beginPath();
      ctx.moveTo(...w.start_px);
      ctx.lineTo(...w.end_px);
      ctx.strokeStyle = COLORS.wall;
      ctx.lineWidth = 2;
      ctx.stroke();
    });

    // entrance
    if (fp.entrance) _drawMarker(ctx, fp.entrance.x_px, fp.entrance.y_px, COLORS.entrance, "E", 10);

    // equipment
    fp.sprinklers.forEach(p => _drawMarker(ctx, p.x_px, p.y_px, COLORS.sprinkler, "S", 8));
    fp.fire_hydrant.forEach(p => _drawMarker(ctx, p.x_px, p.y_px, COLORS.hydrant, "H", 8));
    fp.electrical_panel.forEach(p => _drawMarker(ctx, p.x_px, p.y_px, COLORS.panel, "P", 8));

    // 스케일 앵커: 확정된 선분 (빨간 점선)
    if (anchorLine) {
      ctx.beginPath();
      ctx.moveTo(...anchorLine.start);
      ctx.lineTo(...anchorLine.end);
      ctx.strokeStyle = "#e91e63";
      ctx.lineWidth = 3;
      ctx.setLineDash([8, 4]);
      ctx.stroke();
      ctx.setLineDash([]);
      [anchorLine.start, anchorLine.end].forEach(([x, y]) => {
        ctx.beginPath();
        ctx.arc(x, y, 5, 0, Math.PI * 2);
        ctx.fillStyle = "#e91e63";
        ctx.fill();
      });
      if (anchorLine.mm > 0) {
        const mx = (anchorLine.start[0] + anchorLine.end[0]) / 2;
        const my = (anchorLine.start[1] + anchorLine.end[1]) / 2;
        ctx.font = "bold 13px sans-serif";
        ctx.textAlign = "center";
        ctx.fillStyle = "#e91e63";
        ctx.fillText(`${anchorLine.mm}mm`, mx, my - 10);
      }
    }

    // 스케일 앵커: 진행 중 1점 표시
    if (anchorPts.length === 1) {
      ctx.beginPath();
      ctx.arc(anchorPts[0][0], anchorPts[0][1], 6, 0, Math.PI * 2);
      ctx.fillStyle = "#e91e63";
      ctx.fill();
    }
  }, [fp, hoverVertex, roomDrawPts, anchorLine, anchorPts]);

  // fp/hover 변경 시 자동 redraw
  useEffect(() => { redraw(); }, [redraw]);

  // ── 이미지 로드 ───────────────────────────────────────────────────────────
  function handleImgLoad() {
    redraw();
  }

  // ── 마우스 이벤트 ─────────────────────────────────────────────────────────
  function handleMouseDown(e: React.MouseEvent<HTMLCanvasElement>) {
    const [mx, my] = canvasXY(e);

    // 추가 모드
    if (addMode) {
      _addPoint(mx, my);
      return;
    }

    // 우클릭 = 삭제
    if (e.button === 2) {
      _removePoint(mx, my);
      return;
    }

    // 드래그 대상 찾기
    const target = _findDragTarget(mx, my);
    if (target) {
      setDragTarget(target);
    }
  }

  function handleMouseMove(e: React.MouseEvent<HTMLCanvasElement>) {
    const [mx, my] = canvasXY(e);

    if (dragTarget) {
      _applyDrag(dragTarget, mx, my);
      redraw();
      return;
    }

    // hover 표시
    const nearVertex = fp.floor_polygon_px.findIndex(([x, y]) => dist(mx, my, x, y) < HIT_RADIUS);
    if (nearVertex !== hoverVertex) {
      setHoverVertex(nearVertex >= 0 ? nearVertex : null);
      redraw();
    }
  }

  function handleMouseUp() {
    if (dragTarget) {
      setDragTarget(null);
      console.debug("[MarkingPage] drag end");
    }
  }

  function handleContextMenu(e: React.MouseEvent) {
    e.preventDefault(); // 우클릭 메뉴 방지
  }

  // ── 드래그 대상 찾기 ──────────────────────────────────────────────────────
  function _findDragTarget(mx: number, my: number): DragTarget {
    // polygon 꼭짓점
    for (let i = 0; i < fp.floor_polygon_px.length; i++) {
      const [x, y] = fp.floor_polygon_px[i];
      if (dist(mx, my, x, y) < HIT_RADIUS) return { type: "vertex", index: i };
    }
    // entrance
    if (fp.entrance && dist(mx, my, fp.entrance.x_px, fp.entrance.y_px) < HIT_RADIUS) {
      return { type: "entrance" };
    }
    // equipment
    for (const kind of ["sprinklers", "fire_hydrant", "electrical_panel"] as const) {
      for (let i = 0; i < fp[kind].length; i++) {
        if (dist(mx, my, fp[kind][i].x_px, fp[kind][i].y_px) < HIT_RADIUS) {
          return { type: "equipment", kind, index: i };
        }
      }
    }
    // inaccessible room 꼭짓점
    for (let ri = 0; ri < fp.inaccessible_rooms.length; ri++) {
      const room = fp.inaccessible_rooms[ri];
      for (let vi = 0; vi < room.polygon_px.length; vi++) {
        const [x, y] = room.polygon_px[vi];
        if (dist(mx, my, x, y) < HIT_RADIUS) {
          return { type: "room_vertex", roomIndex: ri, vertexIndex: vi };
        }
      }
    }
    return null;
  }

  // ── 드래그 적용 ───────────────────────────────────────────────────────────
  function _applyDrag(target: NonNullable<DragTarget>, mx: number, my: number) {
    setFp(prev => {
      const next = structuredClone(prev);
      if (target.type === "vertex") {
        next.floor_polygon_px[target.index] = [mx, my];
      } else if (target.type === "entrance" && next.entrance) {
        next.entrance = { ...next.entrance, x_px: mx, y_px: my };
      } else if (target.type === "equipment") {
        next[target.kind][target.index] = { ...next[target.kind][target.index], x_px: mx, y_px: my };
      } else if (target.type === "room_vertex") {
        next.inaccessible_rooms[target.roomIndex].polygon_px[target.vertexIndex] = [mx, my];
      }
      return next;
    });
  }

  // ── 추가 모드 ─────────────────────────────────────────────────────────────
  function _addPoint(mx: number, my: number) {
    // 스케일 앵커: 2점 클릭 → mm 입력 팝업
    if (addMode === "scale_anchor") {
      const pts = [...anchorPts, [mx, my] as [number, number]];
      setAnchorPts(pts);
      if (pts.length >= 2) {
        setAnchorPts([]);
        setAddMode(null);
        setAnchorLine({ start: pts[0], end: pts[1], mm: 0 });
        setAnchorInput(true); // mm 입력 팝업 열기
      }
      requestAnimationFrame(redraw);
      return;
    }

    // inaccessible room: 클릭 4회로 사각형 완성
    if (addMode === "inaccessible") {
      const pts = [...roomDrawPts, [mx, my] as [number, number]];
      setRoomDrawPts(pts);
      if (pts.length >= 4) {
        setFp(prev => {
          const next = structuredClone(prev);
          next.inaccessible_rooms.push({ polygon_px: pts, confidence: "manual" });
          return next;
        });
        setRoomDrawPts([]);
        setAddMode(null);
      }
      requestAnimationFrame(redraw);
      return;
    }

    setFp(prev => {
      const next = structuredClone(prev);
      const pt: DetectedPoint = { x_px: mx, y_px: my, confidence: "manual" };
      if (addMode === "entrance") {
        next.entrance = pt;
      } else if (addMode === "sprinkler") {
        next.sprinklers.push(pt);
      } else if (addMode === "hydrant") {
        next.fire_hydrant.push(pt);
      } else if (addMode === "panel") {
        next.electrical_panel.push(pt);
      }
      return next;
    });
    setAddMode(null);
    requestAnimationFrame(redraw);
  }

  // ── 우클릭 삭제 ──────────────────────────────────────────────────────────
  function _removePoint(mx: number, my: number) {
    setFp(prev => {
      const next = structuredClone(prev);
      // entrance
      if (next.entrance && dist(mx, my, next.entrance.x_px, next.entrance.y_px) < HIT_RADIUS) {
        next.entrance = null;
        return next;
      }
      // equipment
      for (const kind of ["sprinklers", "fire_hydrant", "electrical_panel"] as const) {
        const idx = next[kind].findIndex((p: DetectedPoint) => dist(mx, my, p.x_px, p.y_px) < HIT_RADIUS);
        if (idx >= 0) {
          next[kind].splice(idx, 1);
          return next;
        }
      }
      // inaccessible room — 우클릭이 room 내부에 있으면 해당 room 삭제
      for (let ri = next.inaccessible_rooms.length - 1; ri >= 0; ri--) {
        const room = next.inaccessible_rooms[ri];
        if (_pointInPolygon(mx, my, room.polygon_px)) {
          next.inaccessible_rooms.splice(ri, 1);
          return next;
        }
      }
      return next;
    });
    requestAnimationFrame(redraw);
  }

  // ── 스케일 앵커 확정 ────────────────────────────────────────────────────
  async function handleAnchorConfirm(mmValue: number) {
    if (!anchorLine || mmValue <= 0) return;
    setAnchorInput(false);
    const line = { ...anchorLine, mm: mmValue };
    setAnchorLine(line);

    try {
      const res = await fetch("/api/scale-correct", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          actual_length_mm: mmValue,
          ref_start_px: line.start,
          ref_end_px: line.end,
        }),
      });
      if (!res.ok) throw new Error(`scale-correct 실패: ${res.status}`);
      const data = await res.json();
      const newScale = data.scale_mm_per_px as number;
      setScale(newScale);
      setScaleInput(String(Math.round(newScale * 100) / 100));
      // 가로/세로 mm도 역산 업데이트
      const xs = fp.floor_polygon_px.map(p => p[0]);
      const ys = fp.floor_polygon_px.map(p => p[1]);
      const pxW = Math.max(...xs) - Math.min(...xs);
      const pxH = Math.max(...ys) - Math.min(...ys);
      setWidthMm(Math.round(pxW * newScale));
      setHeightMm(Math.round(pxH * newScale));
      console.debug("[MarkingPage] anchor scale:", newScale, "mm/px");
    } catch (e) {
      console.error("[MarkingPage] anchor scale failed:", e);
    }
  }

  // ── 확정 ──────────────────────────────────────────────────────────────────
  async function handleConfirm() {
    setLoading(true);
    try {
      const userDims = (widthMm > 0 && heightMm > 0)
        ? { width_mm: widthMm, height_mm: heightMm }
        : undefined;
      const sd = await buildSpaceData(currentDrawings, scale, undefined, userDims);
      onComplete(sd, scale);
    } finally {
      setLoading(false);
    }
  }

  // ── 렌더 ──────────────────────────────────────────────────────────────────
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
          <button
            key={mode}
            style={{
              ...styles.addBtn,
              background: addMode === mode ? (mode === "scale_anchor" ? "#e91e63" : "#1a1a1a") : "#fff",
              color: addMode === mode ? "#fff" : "#333",
              borderColor: mode === "scale_anchor" ? "#e91e63" : "#ccc",
            }}
            onClick={() => { setAddMode(addMode === mode ? null : mode); setRoomDrawPts([]); setAnchorPts([]); }}
          >
            {mode === "scale_anchor"
              ? (anchorPts.length === 1 ? "스케일 앵커 (1/2)" : "스케일 앵커")
              : mode === "panel" ? "+ electrical panel"
              : `+ ${mode}`}
            {mode === "inaccessible" && roomDrawPts.length > 0 ? ` (${roomDrawPts.length}/4)` : ""}
          </button>
        ))}
      </div>

      {/* 스케일 앵커 mm 입력 팝업 */}
      {anchorInput && anchorLine && (
        <div style={styles.anchorPopup}>
          <span style={{ fontSize: 13, fontWeight: 600 }}>
            선분 길이: {Math.round(Math.hypot(
              anchorLine.end[0] - anchorLine.start[0],
              anchorLine.end[1] - anchorLine.start[1]
            ))}px — 실제 길이(mm)를 입력하세요
          </span>
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <input
              type="number"
              placeholder="예: 2000"
              autoFocus
              style={styles.input}
              onKeyDown={e => {
                if (e.key === "Enter") {
                  const v = parseFloat((e.target as HTMLInputElement).value) || 0;
                  if (v > 0) handleAnchorConfirm(v);
                }
              }}
            />
            <button
              style={{ ...styles.addBtn, background: "#e91e63", color: "#fff", borderColor: "#e91e63" }}
              onClick={() => {
                const input = document.querySelector<HTMLInputElement>("[placeholder='예: 2000']");
                const v = parseFloat(input?.value ?? "") || 0;
                if (v > 0) handleAnchorConfirm(v);
              }}
            >
              적용
            </button>
            <button
              style={styles.addBtn}
              onClick={() => { setAnchorInput(false); setAnchorLine(null); }}
            >
              취소
            </button>
          </div>
        </div>
      )}

      {/* 도면 + 인터랙티브 canvas */}
      <div ref={useRef<HTMLDivElement>(null)} style={{ position: "relative", overflowX: "auto", border: "1px solid #e0e0e0", borderRadius: 8 }}>
        <img
          ref={imgRef}
          src={imgUrl}
          alt="floor plan"
          onLoad={handleImgLoad}
          style={{ maxWidth: "100%", display: "block" }}
        />
        <canvas
          ref={canvasRef}
          onMouseDown={handleMouseDown}
          onMouseMove={handleMouseMove}
          onMouseUp={handleMouseUp}
          onMouseLeave={handleMouseUp}
          onContextMenu={handleContextMenu}
          style={{
            position: "absolute",
            top: 0,
            left: 0,
            maxWidth: "100%",
            cursor: addMode ? "crosshair" : dragTarget ? "grabbing" : hoverVertex !== null ? "grab" : "default",
          }}
        />
      </div>

      {/* scale 입력 */}
      <div style={styles.scaleRow}>
        <span style={{ fontSize: 14 }}>
          Scale {fp.scale_confirmed
            ? `(Vision 추정: ${Math.round(scale * 10) / 10}mm/px)`
            : "미확인 — 실제 치수 직접 입력 권장"}
        </span>
        <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
          <label style={{ fontSize: 13 }}>가로 (mm)</label>
          <input
            type="number" style={styles.input} placeholder="예: 12000"
            value={widthMm || ""}
            onChange={e => {
              const w = parseFloat(e.target.value) || 0;
              setWidthMm(w);
              _recalcScale(w, heightMm, fp, setScale, setScaleInput);
            }}
          />
          <label style={{ fontSize: 13 }}>세로 (mm)</label>
          <input
            type="number" style={styles.input} placeholder="예: 8000"
            value={heightMm || ""}
            onChange={e => {
              const h = parseFloat(e.target.value) || 0;
              setHeightMm(h);
              _recalcScale(widthMm, h, fp, setScale, setScaleInput);
            }}
          />
          <span style={{ fontSize: 13, color: "#555" }}>{scaleInput} mm/px</span>
        </div>
      </div>

      {/* 편집 요약 */}
      <div style={{ fontSize: 12, color: "#888", marginTop: 8 }}>
        polygon {fp.floor_polygon_px.length}점 · entrance {fp.entrance ? "O" : "X"} ·
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

// ── 헬퍼 ────────────────────────────────────────────────────────────────────

function _drawMarker(ctx: CanvasRenderingContext2D, x: number, y: number, color: string, label: string, r: number) {
  ctx.beginPath();
  ctx.arc(x, y, r, 0, Math.PI * 2);
  ctx.fillStyle = color;
  ctx.fill();
  ctx.strokeStyle = "#fff";
  ctx.lineWidth = 2;
  ctx.stroke();
  ctx.fillStyle = "#fff";
  ctx.font = `bold ${r}px sans-serif`;
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText(label, x, y);
}

function _recalcScale(
  wMm: number, hMm: number, fp: ParsedFloorPlan,
  setScale: (s: number) => void, setScaleInput: (s: string) => void,
) {
  const xs = fp.floor_polygon_px.map(p => p[0]);
  const ys = fp.floor_polygon_px.map(p => p[1]);
  const pxW = Math.max(...xs) - Math.min(...xs);
  const pxH = Math.max(...ys) - Math.min(...ys);
  const scales: number[] = [];
  if (wMm > 0 && pxW > 0) scales.push(wMm / pxW);
  if (hMm > 0 && pxH > 0) scales.push(hMm / pxH);
  if (scales.length > 0) {
    const avg = scales.reduce((a, b) => a + b) / scales.length;
    setScale(avg);
    setScaleInput(String(Math.round(avg * 100) / 100));
  }
}

function _pointInPolygon(px: number, py: number, polygon: [number, number][]): boolean {
  let inside = false;
  for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
    const [xi, yi] = polygon[i];
    const [xj, yj] = polygon[j];
    if ((yi > py) !== (yj > py) && px < ((xj - xi) * (py - yi)) / (yj - yi) + xi) {
      inside = !inside;
    }
  }
  return inside;
}

const styles: Record<string, React.CSSProperties> = {
  container: { maxWidth: 900, margin: "40px auto", padding: "0 24px", fontFamily: "sans-serif" },
  title:     { fontSize: 22, fontWeight: 700, marginBottom: 8 },
  toolbar:   { display: "flex", flexWrap: "wrap", gap: 12, marginBottom: 12, alignItems: "center" },
  addBtn:    { fontSize: 11, padding: "4px 10px", border: "1px solid #ccc", borderRadius: 4, cursor: "pointer" },
  scaleRow:  { marginTop: 16, display: "flex", flexDirection: "column", gap: 8,
               padding: 16, background: "#f5f5f5", borderRadius: 8 },
  input:     { padding: "6px 10px", border: "1px solid #ccc", borderRadius: 4, width: 120 },
  button:    { marginTop: 20, width: "100%", padding: "14px 0", background: "#1a1a1a",
               color: "#fff", border: "none", borderRadius: 8, fontSize: 16,
               fontWeight: 600, cursor: "pointer" },
  anchorPopup: { marginBottom: 12, padding: 16, background: "#fce4ec", borderRadius: 8,
                 display: "flex", flexDirection: "column" as const, gap: 8 },
};
