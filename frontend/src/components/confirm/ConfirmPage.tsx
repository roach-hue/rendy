import { useCallback, useEffect, useMemo, useRef, useState } from "react";

interface ConfirmPageProps {
  spaceData: Record<string, unknown>;
  brandData: Record<string, unknown>;
  scale: number;
  floorFile: File;
  previewBase64?: string;
  onConfirm: () => void;
}

const ZONE_COLORS: Record<string, string> = {
  entrance_zone: "#4caf50",
  mid_zone:      "#ff9800",
  deep_zone:     "#2196f3",
};

export function ConfirmPage({ spaceData, brandData, scale, floorFile, previewBase64, onConfirm }: ConfirmPageProps) {
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

  // zone 컬러맵 그리기
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

    const [oxMm, oyMm] = originOffset ?? [0, 0];

    // slot을 zone별로 그룹화
    const zonePoints: Record<string, [number, number][]> = {};
    for (const [, slot] of slots) {
      const s = slot as Record<string, unknown>;
      const zone = String(s.zone_label);
      const xPx = ((s.x_mm as number) + oxMm) / scale;
      const yPx = ((s.y_mm as number) + oyMm) / scale;
      if (!zonePoints[zone]) zonePoints[zone] = [];
      zonePoints[zone].push([xPx, yPx]);
    }

    // 각 zone의 convex hull → 반투명 채움
    for (const [zone, points] of Object.entries(zonePoints)) {
      if (points.length < 3) continue;
      const hull = _convexHull(points);
      const color = ZONE_COLORS[zone] ?? "#999";

      // 영역을 확장 (padding) — slot이 벽면이라 내부로 넓혀야 자연스러움
      const expanded = _expandHull(hull, 80);

      ctx.beginPath();
      ctx.moveTo(expanded[0][0], expanded[0][1]);
      for (let i = 1; i < expanded.length; i++) {
        ctx.lineTo(expanded[i][0], expanded[i][1]);
      }
      ctx.closePath();
      ctx.fillStyle = color + "30"; // 투명도 ~19%
      ctx.fill();
      ctx.strokeStyle = color + "60";
      ctx.lineWidth = 2;
      ctx.stroke();

      // zone 라벨
      const cx = points.reduce((s, p) => s + p[0], 0) / points.length;
      const cy = points.reduce((s, p) => s + p[1], 0) / points.length;
      ctx.font = "bold 14px sans-serif";
      ctx.textAlign = "center";
      ctx.fillStyle = color;
      ctx.fillText(zone.replace("_", " "), cx, cy);
    }

    console.debug("[ConfirmPage] zone map drawn:", Object.keys(zonePoints));
  }, [slots, scale, originOffset]);

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

// ── Convex Hull (Graham Scan) ───────────────────────────────────────────────

function _convexHull(points: [number, number][]): [number, number][] {
  if (points.length < 3) return [...points];

  const sorted = [...points].sort((a, b) => a[0] - b[0] || a[1] - b[1]);

  function cross(o: [number, number], a: [number, number], b: [number, number]) {
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]);
  }

  const lower: [number, number][] = [];
  for (const p of sorted) {
    while (lower.length >= 2 && cross(lower[lower.length - 2], lower[lower.length - 1], p) <= 0)
      lower.pop();
    lower.push(p);
  }

  const upper: [number, number][] = [];
  for (const p of sorted.reverse()) {
    while (upper.length >= 2 && cross(upper[upper.length - 2], upper[upper.length - 1], p) <= 0)
      upper.pop();
    upper.push(p);
  }

  return [...lower.slice(0, -1), ...upper.slice(0, -1)];
}

function _expandHull(hull: [number, number][], padding: number): [number, number][] {
  // centroid 기준으로 각 꼭짓점을 바깥으로 밀어냄
  const cx = hull.reduce((s, p) => s + p[0], 0) / hull.length;
  const cy = hull.reduce((s, p) => s + p[1], 0) / hull.length;
  return hull.map(([x, y]) => {
    const dx = x - cx;
    const dy = y - cy;
    const len = Math.hypot(dx, dy) || 1;
    return [x + (dx / len) * padding, y + (dy / len) * padding] as [number, number];
  });
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
