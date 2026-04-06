/**
 * 캔버스 상태 관리 + 이벤트 핸들링 + 그리기.
 * 드래그, 추가/삭제, hover, inaccessible room 그리기.
 *
 * DXF 좌표계 대응:
 *   DXF는 mm 단위 좌표 (Y-up). Preview PNG는 matplotlib이 자체 viewport로 렌더링.
 *   dxf_viewport가 있으면 DXF 좌표→이미지 픽셀 변환을 적용.
 *   이미지 파일(PNG/JPG)이면 좌표 = 픽셀 그대로 사용 (기존 동작).
 */
import { useCallback, useEffect, useRef, useState } from "react";
import type { ParsedFloorPlan, DetectedPoint, DetectedEntrance, DxfViewport } from "../../api/detect";

export type DragTarget =
  | { type: "vertex"; index: number }
  | { type: "entrance"; index: number }
  | { type: "equipment"; kind: "sprinklers" | "fire_hydrant" | "electrical_panel"; index: number }
  | { type: "room_vertex"; roomIndex: number; vertexIndex: number }
  | null;

export type AddMode = "entrance" | "sprinkler" | "hydrant" | "panel" | "inaccessible" | "scale_anchor" | null;

const HIT_RADIUS = 14;
const VERTEX_RADIUS = 6;

const COLORS: Record<string, string> = {
  floor: "#2196f3", vertex: "#1565c0", vertexHover: "#e91e63",
  entrance: "#4caf50", sprinkler: "#ff9800", hydrant: "#f44336",
  panel: "#9c27b0", wall: "#795548", inaccessible: "rgba(0,0,0,0.25)",
};

export { COLORS };

function dist(ax: number, ay: number, bx: number, by: number) {
  return Math.hypot(ax - bx, ay - by);
}

export function pointInPolygon(px: number, py: number, polygon: [number, number][]): boolean {
  let inside = false;
  for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
    const [xi, yi] = polygon[i];
    const [xj, yj] = polygon[j];
    if ((yi > py) !== (yj > py) && px < ((xj - xi) * (py - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}

/** 점을 polygon의 가장 가까운 edge 위로 스냅. */
function snapToNearestEdge(px: number, py: number, polygon: [number, number][]): [number, number] {
  let bestDist = Infinity;
  let bestX = px, bestY = py;

  for (let i = 0; i < polygon.length; i++) {
    const j = (i + 1) % polygon.length;
    const [ax, ay] = polygon[i];
    const [bx, by] = polygon[j];
    const dx = bx - ax, dy = by - ay;
    const len2 = dx * dx + dy * dy;
    if (len2 === 0) continue;

    // edge 위의 최근접점 파라미터 t (0~1 클램프)
    let t = ((px - ax) * dx + (py - ay) * dy) / len2;
    t = Math.max(0, Math.min(1, t));

    const cx = ax + t * dx;
    const cy = ay + t * dy;
    const d = dist(px, py, cx, cy);
    if (d < bestDist) {
      bestDist = d;
      bestX = cx;
      bestY = cy;
    }
  }

  return [bestX, bestY];
}

export function drawMarker(ctx: CanvasRenderingContext2D, x: number, y: number, color: string, label: string, r: number) {
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

/**
 * DXF 좌표 ↔ 캔버스 픽셀 변환기.
 * dxf_viewport가 없으면 identity (이미지 파일 모드).
 */
interface CoordMapper {
  toCanvas: (dxfX: number, dxfY: number) => [number, number];
  toDxf: (canvasX: number, canvasY: number) => [number, number];
  isDxf: boolean;
}

function createCoordMapper(
  viewport: DxfViewport | undefined,
  canvasW: number,
  canvasH: number,
): CoordMapper {
  if (!viewport || canvasW === 0 || canvasH === 0) {
    return {
      toCanvas: (x, y) => [x, y],
      toDxf: (x, y) => [x, y],
      isDxf: false,
    };
  }

  // 백엔드가 pad_inches=0 + 명시적 axis limits로 렌더링하므로
  // viewport가 이미지와 정확히 1:1 대응.
  // matplotlib aspect="equal" → 짧은 축에 여백이 생김
  const vw = viewport.max_x - viewport.min_x;
  const vh = viewport.max_y - viewport.min_y;

  const scaleX = canvasW / vw;
  const scaleY = canvasH / vh;
  const scale = Math.min(scaleX, scaleY);

  // aspect="equal"로 인한 중앙 정렬 오프셋
  const usedW = vw * scale;
  const usedH = vh * scale;
  const offsetX = (canvasW - usedW) / 2;
  const offsetY = (canvasH - usedH) / 2;

  return {
    toCanvas: (dxfX: number, dxfY: number) => {
      // DXF Y-up → 캔버스 Y-down
      const cx = offsetX + (dxfX - viewport.min_x) * scale;
      const cy = canvasH - (offsetY + (dxfY - viewport.min_y) * scale);
      return [cx, cy];
    },
    toDxf: (canvasX: number, canvasY: number) => {
      const dxfX = (canvasX - offsetX) / scale + viewport.min_x;
      const dxfY = ((canvasH - canvasY) - offsetY) / scale + viewport.min_y;
      return [dxfX, dxfY];
    },
    isDxf: true,
  };
}


interface UseMarkingCanvasArgs {
  fp: ParsedFloorPlan;
  setFp: React.Dispatch<React.SetStateAction<ParsedFloorPlan>>;
  addMode: AddMode;
  setAddMode: (m: AddMode) => void;
  dxfViewport?: DxfViewport;
  anchorPts: [number, number][];
  setAnchorPts: (pts: [number, number][]) => void;
  anchorLine: { start: [number, number]; end: [number, number]; mm: number } | null;
  setAnchorLine: (v: { start: [number, number]; end: [number, number]; mm: number } | null) => void;
  setAnchorInput: (v: boolean) => void;
  roomDrawPts: [number, number][];
  setRoomDrawPts: (pts: [number, number][]) => void;
}

export function useMarkingCanvas({
  fp, setFp, addMode, setAddMode, dxfViewport,
  anchorPts, setAnchorPts, anchorLine, setAnchorLine, setAnchorInput,
  roomDrawPts, setRoomDrawPts,
}: UseMarkingCanvasArgs) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const imgRef = useRef<HTMLImageElement>(null);
  const [dragTarget, setDragTarget] = useState<DragTarget>(null);
  const [hoverVertex, setHoverVertex] = useState<number | null>(null);
  const mapperRef = useRef<CoordMapper>({ toCanvas: (x, y) => [x, y], toDxf: (x, y) => [x, y], isDxf: false });

  // ── 좌표 변환 ─────────────────────────────────────────────────────────────
  function canvasXY(e: React.MouseEvent<HTMLCanvasElement>): [number, number] {
    const canvas = canvasRef.current!;
    const rect = canvas.getBoundingClientRect();
    return [(e.clientX - rect.left) * (canvas.width / rect.width),
            (e.clientY - rect.top) * (canvas.height / rect.height)];
  }

  /** 데이터 좌표(px/mm) → 캔버스 픽셀 */
  function toC(x: number, y: number): [number, number] {
    return mapperRef.current.toCanvas(x, y);
  }

  /** 캔버스 픽셀 → 데이터 좌표 */
  function toD(x: number, y: number): [number, number] {
    return mapperRef.current.toDxf(x, y);
  }

  // ── 그리기 ────────────────────────────────────────────────────────────────
  const redraw = useCallback(() => {
    const canvas = canvasRef.current;
    const img = imgRef.current;
    if (!canvas || !img) return;
    canvas.width = img.naturalWidth;
    canvas.height = img.naturalHeight;

    // mapper 초기화
    mapperRef.current = createCoordMapper(dxfViewport, canvas.width, canvas.height);

    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    const m = mapperRef.current;

    // polygon + 꼭짓점
    if (fp.floor_polygon_px.length > 2) {
      ctx.beginPath();
      const [sx, sy] = m.toCanvas(...fp.floor_polygon_px[0]);
      ctx.moveTo(sx, sy);
      fp.floor_polygon_px.slice(1).forEach(p => {
        const [cx, cy] = m.toCanvas(...p);
        ctx.lineTo(cx, cy);
      });
      ctx.closePath();
      ctx.strokeStyle = COLORS.floor; ctx.lineWidth = 2; ctx.stroke();
      ctx.fillStyle = COLORS.floor + "10"; ctx.fill();
      fp.floor_polygon_px.forEach(([x, y], i) => {
        const [cx, cy] = m.toCanvas(x, y);
        ctx.beginPath(); ctx.arc(cx, cy, VERTEX_RADIUS, 0, Math.PI * 2);
        ctx.fillStyle = i === hoverVertex ? COLORS.vertexHover : COLORS.vertex;
        ctx.fill(); ctx.strokeStyle = "#fff"; ctx.lineWidth = 2; ctx.stroke();
      });
    }

    // inaccessible rooms
    fp.inaccessible_rooms.forEach(r => {
      ctx.beginPath();
      const [rx, ry] = m.toCanvas(...r.polygon_px[0]);
      ctx.moveTo(rx, ry);
      r.polygon_px.slice(1).forEach(p => {
        const [px, py] = m.toCanvas(...p);
        ctx.lineTo(px, py);
      });
      ctx.closePath(); ctx.fillStyle = COLORS.inaccessible; ctx.fill();
      ctx.strokeStyle = "#000"; ctx.lineWidth = 1; ctx.stroke();
      r.polygon_px.forEach(([x, y]) => {
        const [cx, cy] = m.toCanvas(x, y);
        ctx.beginPath(); ctx.arc(cx, cy, 4, 0, Math.PI * 2); ctx.fillStyle = "#d32f2f"; ctx.fill();
      });
    });

    // room draw in progress
    if (roomDrawPts.length > 0) {
      ctx.beginPath(); ctx.moveTo(...roomDrawPts[0]);
      roomDrawPts.slice(1).forEach(p => ctx.lineTo(...p));
      ctx.strokeStyle = "#d32f2f"; ctx.lineWidth = 2; ctx.setLineDash([6, 4]); ctx.stroke(); ctx.setLineDash([]);
      roomDrawPts.forEach(([x, y]) => { ctx.beginPath(); ctx.arc(x, y, 5, 0, Math.PI * 2); ctx.fillStyle = "#d32f2f"; ctx.fill(); });
    }

    // inner walls
    fp.inner_walls.forEach(w => {
      const [sx2, sy2] = m.toCanvas(...w.start_px);
      const [ex2, ey2] = m.toCanvas(...w.end_px);
      ctx.beginPath(); ctx.moveTo(sx2, sy2); ctx.lineTo(ex2, ey2);
      ctx.strokeStyle = COLORS.wall; ctx.lineWidth = 2; ctx.stroke();
    });

    // entrance markers — entrances 배열 우선, fallback entrance 단일
    // polygon 외부이면 최근접 edge로 시각적 스냅
    const entrances = fp.entrances?.length ? fp.entrances : (fp.entrance ? [fp.entrance] : []);
    const polyCanvas = fp.floor_polygon_px.map(([x, y]) => m.toCanvas(x, y));
    entrances.forEach((ent) => {
      let [cx, cy] = m.toCanvas(ent.x_px, ent.y_px);
      // polygon 외부이면 최근접 edge로 스냅 (시각적 only)
      if (polyCanvas.length >= 3 && !pointInPolygon(cx, cy, polyCanvas as [number, number][])) {
        [cx, cy] = snapToNearestEdge(cx, cy, polyCanvas as [number, number][]);
      }
      const label = "is_main" in ent && !ent.is_main ? "X" : "E";
      drawMarker(ctx, cx, cy, COLORS.entrance, label, 10);
    });

    // equipment markers
    fp.sprinklers.forEach(p => {
      const [cx, cy] = m.toCanvas(p.x_px, p.y_px);
      drawMarker(ctx, cx, cy, COLORS.sprinkler, "S", 8);
    });
    fp.fire_hydrant.forEach(p => {
      const [cx, cy] = m.toCanvas(p.x_px, p.y_px);
      drawMarker(ctx, cx, cy, COLORS.hydrant, "H", 8);
    });
    fp.electrical_panel.forEach(p => {
      const [cx, cy] = m.toCanvas(p.x_px, p.y_px);
      drawMarker(ctx, cx, cy, COLORS.panel, "P", 8);
    });

    // anchor line
    if (anchorLine) {
      ctx.beginPath(); ctx.moveTo(...anchorLine.start); ctx.lineTo(...anchorLine.end);
      ctx.strokeStyle = "#e91e63"; ctx.lineWidth = 3; ctx.setLineDash([8, 4]); ctx.stroke(); ctx.setLineDash([]);
      [anchorLine.start, anchorLine.end].forEach(([x, y]) => { ctx.beginPath(); ctx.arc(x, y, 5, 0, Math.PI * 2); ctx.fillStyle = "#e91e63"; ctx.fill(); });
      if (anchorLine.mm > 0) {
        const mx = (anchorLine.start[0] + anchorLine.end[0]) / 2;
        const my = (anchorLine.start[1] + anchorLine.end[1]) / 2;
        ctx.font = "bold 13px sans-serif"; ctx.textAlign = "center"; ctx.fillStyle = "#e91e63";
        ctx.fillText(`${anchorLine.mm}mm`, mx, my - 10);
      }
    }
    if (anchorPts.length === 1) { ctx.beginPath(); ctx.arc(anchorPts[0][0], anchorPts[0][1], 6, 0, Math.PI * 2); ctx.fillStyle = "#e91e63"; ctx.fill(); }
  }, [fp, hoverVertex, roomDrawPts, anchorLine, anchorPts, dxfViewport]);

  useEffect(() => { redraw(); }, [redraw]);

  // ── 이벤트 핸들러 ─────────────────────────────────────────────────────────
  function findDragTarget(mx: number, my: number): DragTarget {
    // polygon 꼭짓점
    for (let i = 0; i < fp.floor_polygon_px.length; i++) {
      const [cx, cy] = toC(...fp.floor_polygon_px[i]);
      if (dist(mx, my, cx, cy) < HIT_RADIUS) return { type: "vertex", index: i };
    }
    // entrances
    const entrances = fp.entrances?.length ? fp.entrances : (fp.entrance ? [fp.entrance] : []);
    for (let i = 0; i < entrances.length; i++) {
      const [cx, cy] = toC(entrances[i].x_px, entrances[i].y_px);
      if (dist(mx, my, cx, cy) < HIT_RADIUS) return { type: "entrance", index: i };
    }
    // equipment
    for (const kind of ["sprinklers", "fire_hydrant", "electrical_panel"] as const) {
      for (let i = 0; i < fp[kind].length; i++) {
        const [cx, cy] = toC(fp[kind][i].x_px, fp[kind][i].y_px);
        if (dist(mx, my, cx, cy) < HIT_RADIUS) return { type: "equipment", kind, index: i };
      }
    }
    // room vertices
    for (let ri = 0; ri < fp.inaccessible_rooms.length; ri++) {
      for (let vi = 0; vi < fp.inaccessible_rooms[ri].polygon_px.length; vi++) {
        const [cx, cy] = toC(...fp.inaccessible_rooms[ri].polygon_px[vi]);
        if (dist(mx, my, cx, cy) < HIT_RADIUS) return { type: "room_vertex", roomIndex: ri, vertexIndex: vi };
      }
    }
    return null;
  }

  function applyDrag(target: NonNullable<DragTarget>, mx: number, my: number) {
    // 캔버스 좌표→데이터 좌표 변환
    const [dx, dy] = toD(mx, my);
    setFp(prev => {
      const next = structuredClone(prev);
      if (target.type === "vertex") {
        next.floor_polygon_px[target.index] = [dx, dy];
      } else if (target.type === "entrance") {
        if (next.entrances?.length > target.index) {
          next.entrances[target.index] = { ...next.entrances[target.index], x_px: dx, y_px: dy };
        }
        // 하위 호환: entrance 단일 필드 동기화
        if (target.index === 0 || !next.entrances?.length) {
          if (next.entrance) next.entrance = { ...next.entrance, x_px: dx, y_px: dy };
        }
      } else if (target.type === "equipment") {
        next[target.kind][target.index] = { ...next[target.kind][target.index], x_px: dx, y_px: dy };
      } else if (target.type === "room_vertex") {
        next.inaccessible_rooms[target.roomIndex].polygon_px[target.vertexIndex] = [dx, dy];
      }
      return next;
    });
  }

  function addPoint(mx: number, my: number) {
    if (addMode === "scale_anchor") {
      const pts = [...anchorPts, [mx, my] as [number, number]];
      setAnchorPts(pts);
      if (pts.length >= 2) { setAnchorPts([]); setAddMode(null); setAnchorLine({ start: pts[0], end: pts[1], mm: 0 }); setAnchorInput(true); }
      return;
    }
    if (addMode === "inaccessible") {
      const pts = [...roomDrawPts, [mx, my] as [number, number]];
      setRoomDrawPts(pts);
      if (pts.length >= 4) {
        // 캔버스 좌표→데이터 좌표 변환
        const dataPts = pts.map(([x, y]) => toD(x, y)) as [number, number][];
        setFp(prev => { const next = structuredClone(prev); next.inaccessible_rooms.push({ polygon_px: dataPts, confidence: "manual" }); return next; });
        setRoomDrawPts([]); setAddMode(null);
      }
      return;
    }
    // 캔버스 좌표→데이터 좌표
    const [dx, dy] = toD(mx, my);
    setFp(prev => {
      const next = structuredClone(prev);
      if (addMode === "entrance") {
        const newEnt: DetectedEntrance = { x_px: dx, y_px: dy, confidence: "manual", is_main: true, type: "MAIN_DOOR" };
        next.entrances = [...(next.entrances || []), newEnt];
        // 하위 호환: entrance 단일 필드도 설정
        next.entrance = { x_px: dx, y_px: dy, confidence: "manual" };
      } else if (addMode === "sprinkler") {
        next.sprinklers.push({ x_px: dx, y_px: dy, confidence: "manual" });
      } else if (addMode === "hydrant") {
        next.fire_hydrant.push({ x_px: dx, y_px: dy, confidence: "manual" });
      } else if (addMode === "panel") {
        next.electrical_panel.push({ x_px: dx, y_px: dy, confidence: "manual" });
      }
      return next;
    });
    setAddMode(null);
  }

  function removePoint(mx: number, my: number) {
    setFp(prev => {
      const next = structuredClone(prev);
      // entrances 배열에서 제거
      if (next.entrances?.length) {
        const idx = next.entrances.findIndex((e: DetectedEntrance) => {
          const [cx, cy] = toC(e.x_px, e.y_px);
          return dist(mx, my, cx, cy) < HIT_RADIUS;
        });
        if (idx >= 0) {
          next.entrances.splice(idx, 1);
          next.entrance = next.entrances.length > 0 ? {
            x_px: next.entrances[0].x_px,
            y_px: next.entrances[0].y_px,
            confidence: next.entrances[0].confidence,
          } : null;
          return next;
        }
      } else if (next.entrance) {
        const [cx, cy] = toC(next.entrance.x_px, next.entrance.y_px);
        if (dist(mx, my, cx, cy) < HIT_RADIUS) { next.entrance = null; return next; }
      }
      for (const kind of ["sprinklers", "fire_hydrant", "electrical_panel"] as const) {
        const idx = next[kind].findIndex((p: DetectedPoint) => {
          const [cx, cy] = toC(p.x_px, p.y_px);
          return dist(mx, my, cx, cy) < HIT_RADIUS;
        });
        if (idx >= 0) { next[kind].splice(idx, 1); return next; }
      }
      for (let ri = next.inaccessible_rooms.length - 1; ri >= 0; ri--) {
        const canvasPoly = next.inaccessible_rooms[ri].polygon_px.map(
          ([x, y]: [number, number]) => toC(x, y)
        );
        if (pointInPolygon(mx, my, canvasPoly)) { next.inaccessible_rooms.splice(ri, 1); return next; }
      }
      return next;
    });
  }

  // ── 통합 핸들러 ───────────────────────────────────────────────────────────
  function handleMouseDown(e: React.MouseEvent<HTMLCanvasElement>) {
    const [mx, my] = canvasXY(e);
    if (addMode) { addPoint(mx, my); return; }
    if (e.button === 2) { removePoint(mx, my); return; }
    const target = findDragTarget(mx, my);
    if (target) setDragTarget(target);
  }

  function handleMouseMove(e: React.MouseEvent<HTMLCanvasElement>) {
    const [mx, my] = canvasXY(e);
    if (dragTarget) { applyDrag(dragTarget, mx, my); return; }
    const near = fp.floor_polygon_px.findIndex(([x, y]) => {
      const [cx, cy] = toC(x, y);
      return dist(mx, my, cx, cy) < HIT_RADIUS;
    });
    if (near !== hoverVertex) setHoverVertex(near >= 0 ? near : null);
  }

  function handleMouseUp() { if (dragTarget) setDragTarget(null); }
  function handleContextMenu(e: React.MouseEvent) { e.preventDefault(); }

  const cursor = addMode ? "crosshair" : dragTarget ? "grabbing" : hoverVertex !== null ? "grab" : "default";

  return {
    canvasRef, imgRef, dragTarget, hoverVertex, cursor,
    handleMouseDown, handleMouseMove, handleMouseUp, handleContextMenu,
    handleImgLoad: redraw,
  };
}
