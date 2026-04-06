export interface DetectedPoint {
  x_px: number;
  y_px: number;
  confidence: string;
}

export interface DetectedSegment {
  start_px: [number, number];
  end_px: [number, number];
  confidence: string;
}

export interface DetectedPolygon {
  polygon_px: [number, number][];
  confidence: string;
}

export interface DetectedEntrance {
  x_px: number;
  y_px: number;
  confidence: string;
  is_main: boolean;
  type: string;
}

export interface ParsedFloorPlan {
  floor_polygon_px: [number, number][];
  scale_mm_per_px: number;
  scale_confirmed: boolean;
  detected_width_mm: number | null;
  detected_height_mm: number | null;
  entrance: DetectedPoint | null;  // 하위 호환: entrances[0]
  entrances: DetectedEntrance[];
  sprinklers: DetectedPoint[];
  fire_hydrant: DetectedPoint[];
  electrical_panel: DetectedPoint[];
  inner_walls: DetectedSegment[];
  inaccessible_rooms: DetectedPolygon[];
}

export interface DxfViewport {
  min_x: number;
  min_y: number;
  max_x: number;
  max_y: number;
}

export interface ParsedDrawings {
  floor_plan: ParsedFloorPlan;
  section: { ceiling_height_mm: number | null } | null;
  preview_image_base64?: string;  // PDF/DXF일 때 래스터화 미리보기
  dxf_viewport?: DxfViewport;    // DXF 도면의 엔티티 bounding box
}

export async function detectFloorPlan(
  floorFile: File,
  sectionFile?: File
): Promise<ParsedDrawings> {
  const form = new FormData();
  form.append("floor_plan", floorFile);
  if (sectionFile) form.append("section_drawing", sectionFile);

  const res = await fetch("/api/detect", { method: "POST", body: form });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail ?? `감지 실패: ${res.status}`);
  }
  return res.json();
}

export async function extractBrand(brandFile: File): Promise<Record<string, unknown>> {
  const form = new FormData();
  form.append("brand_manual", brandFile);

  const res = await fetch("/api/brand", { method: "POST", body: form });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail ?? `브랜드 추출 실패: ${res.status}`);
  }
  return res.json();
}

export async function buildSpaceData(
  drawings: ParsedDrawings,
  scaleMmPerPx: number,
  entrancePx?: [number, number],
  userDims?: { width_mm: number; height_mm: number },
): Promise<Record<string, unknown>> {
  const res = await fetch("/api/space-data", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      drawings,
      scale_mm_per_px: scaleMmPerPx,
      entrance_px: entrancePx ?? null,
      user_dims: userDims ?? null,
    }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail ?? `공간 연산 실패: ${res.status}`);
  }
  return res.json();
}
