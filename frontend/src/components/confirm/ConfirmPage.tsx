import { useCallback, useEffect, useMemo, useRef } from "react";
import type { DxfViewport, DetectedPolygon } from "../../api/detect";

interface ConfirmPageProps {
  spaceData: Record<string, unknown>;
  brandData: Record<string, unknown>;
  scale: number;
  floorFile: File;
  previewBase64?: string;
  dxfViewport?: DxfViewport;
  floorPolygonPx?: [number, number][];
  inaccessibleRooms?: DetectedPolygon[];
  onConfirm: () => void;
}

const ZONE_COLORS: Record<string, string> = {
  entrance_zone: "#4caf50",
  mid_zone:      "#ff9800",
  deep_zone:     "#2196f3",
};

export function ConfirmPage({ spaceData, brandData, scale, floorFile, previewBase64, dxfViewport, floorPolygonPx, inaccessibleRooms, onConfirm }: ConfirmPageProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const imgRef = useRef<HTMLImageElement>(null);

  const floor = spaceData.floor as Record<string, unknown> | undefined;
  const fire  = spaceData.fire  as Record<string, unknown> | undefined;

  const slots = useMemo(() =>
    Object.entries(spaceData)
      .filter(([k, v]) => typeof v === "object" && v !== null && "zone_label" in (v as object) && k !== "floor"),
    [spaceData],
  );

  const brandFields = [
    { key: "clearspace_mm",         label: "이격 거리" },
    { key: "logo_clearspace_mm",    label: "로고 여백" },
    { key: "character_orientation", label: "배치 방향" },
    { key: "prohibited_material",   label: "금지 소재" },
  ];

  const pairRules = (brandData.object_pair_rules as { rule: string; confidence: string }[] | undefined) ?? [];

  const imgUrl = useMemo(() => {
    if (previewBase64) return `data:image/png;base64,${previewBase64}`;
    return URL.createObjectURL(floorFile);
  }, [floorFile, previewBase64]);

  const originOffset = spaceData._origin_offset_mm as [number, number] | undefined;

  // mm 좌표 → 캔버스 픽셀 변환
  const toCanvas = useCallback((xMm: number, yMm: number, canvasW: number, canvasH: number): [number, number] => {
    if (dxfViewport && canvasW > 0 && canvasH > 0) {
      // DXF 모드: viewport 기반 변환 (Y 반전)
      const vw = dxfViewport.max_x - dxfViewport.min_x;
      const vh = dxfViewport.max_y - dxfViewport.min_y;
      const scX = canvasW / vw;
      const scY = canvasH / vh;
      const sc = Math.min(scX, scY);
      const offX = (canvasW - vw * sc) / 2;
      const offY = (canvasH - vh * sc) / 2;
      // space_data의 mm 좌표는 원점 정규화 후 (0,0 기준)
      // dxf_viewport는 DXF 원본 좌표 기준이므로, origin_offset 역산 필요
      const [oxMm, oyMm] = originOffset ?? [0, 0];
      const dxfX = xMm + oxMm;
      const dxfY = yMm + oyMm;
      const cx = offX + (dxfX - dxfViewport.min_x) * sc;
      const cy = canvasH - (offY + (dxfY - dxfViewport.min_y) * sc);
      return [cx, cy];
    }
    // 이미지 모드: mm → px 직접 변환
    const [oxMm, oyMm] = originOffset ?? [0, 0];
    return [((xMm) + oxMm) / scale, ((yMm) + oyMm) / scale];
  }, [dxfViewport, originOffset, scale]);

  // floor polygon → 캔버스 좌표 (clip + point-in-polygon 용)
  const getFloorCanvasPath = useCallback((w: number, h: number): [number, number][] | null => {
    if (!floorPolygonPx || floorPolygonPx.length < 3) return null;
    return floorPolygonPx.map(([x, y]) => toCanvas(x, y, w, h));
  }, [floorPolygonPx, toCanvas]);

  // inaccessible rooms → 캔버스 좌표
  const getInaccessiblePaths = useCallback((w: number, h: number): [number, number][][] => {
    if (!inaccessibleRooms) return [];
    return inaccessibleRooms.map(room =>
      room.polygon_px.map(([x, y]) => toCanvas(x, y, w, h))
    );
  }, [inaccessibleRooms, toCanvas]);

  // zone 컬러맵 — Voronoi grid fill + floor polygon clip + inaccessible 차감
  const drawZoneMap = useCallback(() => {
    const img = imgRef.current;
    const canvas = canvasRef.current;
    if (!img || !canvas) return;
    const w = img.naturalWidth;
    const h = img.naturalHeight;
    canvas.width = w;
    canvas.height = h;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.clearRect(0, 0, w, h);

    // slot → 캔버스 좌표 + zone 매핑
    const slotData: { cx: number; cy: number; zone: string }[] = [];
    for (const [, slot] of slots) {
      const s = slot as Record<string, unknown>;
      const [cx, cy] = toCanvas(s.x_mm as number, s.y_mm as number, w, h);
      slotData.push({ cx, cy, zone: String(s.zone_label) });
    }

    if (slotData.length === 0) return;

    // floor polygon 캔버스 좌표 (clip용)
    const floorPath = getFloorCanvasPath(w, h);
    const inaccessiblePaths = getInaccessiblePaths(w, h);

    // 저해상도 offscreen canvas로 Voronoi grid fill
    const GRID = 4;
    const gridW = Math.ceil(w / GRID);
    const gridH = Math.ceil(h / GRID);
    const offscreen = document.createElement("canvas");
    offscreen.width = gridW;
    offscreen.height = gridH;
    const offCtx = offscreen.getContext("2d")!;

    const zoneRgba: Record<string, [number, number, number]> = {
      entrance_zone: [76, 175, 80],
      mid_zone: [255, 152, 0],
      deep_zone: [33, 150, 243],
    };

    const imageData = offCtx.createImageData(gridW, gridH);
    const data = imageData.data;

    for (let gy = 0; gy < gridH; gy++) {
      for (let gx = 0; gx < gridW; gx++) {
        const px = gx * GRID;
        const py = gy * GRID;

        // floor polygon 내부인지 체크
        if (floorPath && !_pointInPoly(px, py, floorPath)) continue;

        // inaccessible room 내부이면 스킵
        let inInaccessible = false;
        for (const path of inaccessiblePaths) {
          if (_pointInPoly(px, py, path)) { inInaccessible = true; break; }
        }
        if (inInaccessible) continue;

        // 최근접 slot → zone 결정
        let bestDist = Infinity;
        let bestZone = "";
        for (const s of slotData) {
          const d = (px - s.cx) ** 2 + (py - s.cy) ** 2;
          if (d < bestDist) { bestDist = d; bestZone = s.zone; }
        }

        const rgb = zoneRgba[bestZone] ?? [153, 153, 153];
        const idx = (gy * gridW + gx) * 4;
        data[idx] = rgb[0];
        data[idx + 1] = rgb[1];
        data[idx + 2] = rgb[2];
        data[idx + 3] = 45;
      }
    }

    offCtx.putImageData(imageData, 0, 0);

    ctx.imageSmoothingEnabled = true;
    ctx.drawImage(offscreen, 0, 0, gridW, gridH, 0, 0, w, h);

    // inaccessible 영역 표시 (사선 해칭)
    for (const path of inaccessiblePaths) {
      if (path.length < 3) continue;
      ctx.beginPath();
      ctx.moveTo(path[0][0], path[0][1]);
      for (let i = 1; i < path.length; i++) ctx.lineTo(path[i][0], path[i][1]);
      ctx.closePath();
      ctx.fillStyle = "rgba(0,0,0,0.08)";
      ctx.fill();
      ctx.strokeStyle = "rgba(0,0,0,0.3)";
      ctx.lineWidth = 1;
      ctx.setLineDash([6, 4]);
      ctx.stroke();
      ctx.setLineDash([]);
    }

    // zone 라벨
    const zoneCenters: Record<string, { sx: number; sy: number; count: number }> = {};
    for (const s of slotData) {
      if (!zoneCenters[s.zone]) zoneCenters[s.zone] = { sx: 0, sy: 0, count: 0 };
      zoneCenters[s.zone].sx += s.cx;
      zoneCenters[s.zone].sy += s.cy;
      zoneCenters[s.zone].count++;
    }
    for (const [zone, c] of Object.entries(zoneCenters)) {
      const cx = c.sx / c.count;
      const cy = c.sy / c.count;
      const rgb = zoneRgba[zone] ?? [153, 153, 153];
      ctx.font = "bold 14px sans-serif";
      ctx.textAlign = "center";
      ctx.fillStyle = `rgb(${rgb[0]},${rgb[1]},${rgb[2]})`;
      ctx.fillText(zone.replace("_", " "), cx, cy);
    }

    console.debug("[ConfirmPage] zone voronoi drawn:", Object.keys(zoneCenters));
  }, [slots, toCanvas, getFloorCanvasPath, getInaccessiblePaths]);

  useEffect(() => { drawZoneMap(); }, [drawZoneMap]);

  function handleImgLoad() {
    drawZoneMap();
  }

  // zone별 slot 수 요약
  const zoneSummary = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const [, slot] of slots) {
      const zone = String((slot as Record<string, unknown>).zone_label);
      counts[zone] = (counts[zone] ?? 0) + 1;
    }
    return counts;
  }, [slots]);

  return (
    <div style={styles.container}>
      <h2 style={styles.title}>공간 검토</h2>
      <p style={styles.sub}>아래 내용을 검토 후 확정하세요. 이후 오브젝트 배치 단계로 넘어갑니다.</p>

      {/* 도면 + zone 컬러맵 */}
      <Section title="배치 영역 (Zone Map)">
        <div style={{ position: "relative", overflowX: "auto" }}>
          <img
            ref={imgRef}
            src={imgUrl}
            alt="floor plan"
            onLoad={handleImgLoad}
            style={{ maxWidth: "100%", display: "block" }}
          />
          <canvas
            ref={canvasRef}
            style={{
              position: "absolute", top: 0, left: 0,
              maxWidth: "100%", pointerEvents: "none",
            }}
          />
        </div>
        <div style={{ padding: "8px 16px", display: "flex", gap: 16, flexWrap: "wrap", alignItems: "center" }}>
          {Object.entries(ZONE_COLORS).map(([zone, color]) => (
            <span key={zone} style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 12 }}>
              <span style={{ width: 12, height: 12, background: color, display: "inline-block", borderRadius: 2 }} />
              {zone.replace("_", " ")} ({zoneSummary[zone] ?? 0} slots)
            </span>
          ))}
        </div>
      </Section>

      {/* 공간 정보 */}
      <Section title="공간 정보">
        <Row label="가용 면적"      value={`${floor?.usable_area_sqm ?? "?"}m\u00B2`} />
        <Row label="천장 높이"      value={_fieldVal(floor?.ceiling_height_mm)} />
        <Row label="최대 오브젝트 너비" value={`${floor?.max_object_w_mm ?? "?"}mm`} />
        <Row label="scale"         value={`${Math.round(scale * 100) / 100} mm/px`} />
        <Row label="소방 주통로"    value={`${fire?.main_corridor_min_mm ?? 900}mm 이상`} />
        <Row label="비상 대피로"    value={`${fire?.emergency_path_min_mm ?? 1200}mm 이상`} />
        <Row label="배치 슬롯"     value={`${slots.length}개`} />
      </Section>

      {/* 브랜드 제약 */}
      <Section title="브랜드 제약">
        {brandFields.map(({ key, label }) => (
          <Row key={key} label={label} value={_fieldVal(brandData[key])} />
        ))}
        {pairRules.length > 0 && (
          <div style={styles.row}>
            <span style={styles.rowLabel}>오브젝트 쌍 규정</span>
            <ul style={{ margin: 0, paddingLeft: 16 }}>
              {pairRules.map((r, i) => (
                <li key={i} style={{ fontSize: 14, color: "#444" }}>
                  {r.rule} <Badge text={r.confidence} />
                </li>
              ))}
            </ul>
          </div>
        )}
      </Section>

      <button style={styles.button} onClick={onConfirm}>
        확정 → 오브젝트 배치 시작
      </button>
    </div>
  );
}

// ── Point-in-polygon (ray casting) ──────────────────────────────────────────

function _pointInPoly(px: number, py: number, poly: [number, number][]): boolean {
  let inside = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const [xi, yi] = poly[i];
    const [xj, yj] = poly[j];
    if ((yi > py) !== (yj > py) && px < ((xj - xi) * (py - yi)) / (yj - yi) + xi)
      inside = !inside;
  }
  return inside;
}


// ── UI 컴포넌트 ──────────────────────────────────────────────────────────────

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div style={{ marginBottom: 24 }}>
      <h3 style={{ fontSize: 16, fontWeight: 700, marginBottom: 12, color: "#111" }}>{title}</h3>
      <div style={{ border: "1px solid #e0e0e0", borderRadius: 8, overflow: "hidden" }}>
        {children}
      </div>
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div style={styles.row}>
      <span style={styles.rowLabel}>{label}</span>
      <span style={{ fontSize: 14, color: "#333" }}>{value}</span>
    </div>
  );
}

function Badge({ text, color = "#666" }: { text: string; color?: string }) {
  return (
    <span style={{ fontSize: 11, background: color + "22", color, padding: "2px 7px",
      borderRadius: 4, fontWeight: 600, marginLeft: 6 }}>
      {text}
    </span>
  );
}

function _fieldVal(field: unknown): string {
  if (!field || typeof field !== "object") return "없음";
  const f = field as { value?: unknown; confidence?: string; source?: string };
  if (f.value == null) return "없음";
  return `${f.value}  (${f.confidence ?? ""} / ${f.source ?? ""})`;
}

const styles: Record<string, React.CSSProperties> = {
  container: { maxWidth: 700, margin: "40px auto", padding: "0 24px", fontFamily: "sans-serif" },
  title:     { fontSize: 22, fontWeight: 700, marginBottom: 8 },
  sub:       { fontSize: 14, color: "#666", marginBottom: 28 },
  row:       { display: "flex", justifyContent: "space-between", alignItems: "flex-start",
               padding: "10px 16px", borderBottom: "1px solid #f0f0f0" },
  rowLabel:  { fontSize: 14, fontWeight: 600, color: "#555", minWidth: 140 },
  button:    { marginTop: 8, width: "100%", padding: "14px 0", background: "#1a1a1a",
               color: "#fff", border: "none", borderRadius: 8, fontSize: 16,
               fontWeight: 600, cursor: "pointer" },
};
