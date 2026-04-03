export interface ViolationItem {
  object_type: string;
  rule: string;
  severity: string;
  detail: string;
}

export interface PlacementResult {
  placed: Record<string, unknown>[];
  dropped: Record<string, unknown>[];
  verification: {
    passed: boolean;
    blocking: ViolationItem[];
    warning: ViolationItem[];
    checked_count: number;
  };
  report: string;
  glb_base64: string;
  log: string[];
  summary: {
    total_area_sqm: number;
    zone_distribution: Record<string, number>;
    placed_count: number;
    dropped_count: number;
    success_rate: number;
    fallback_used: boolean;
    slot_count: number;
    verification_passed: boolean;
  };
}

export async function runPlacement(
  spaceData: Record<string, unknown>,
  brandData: Record<string, unknown>,
  scaleMmPerPx: number,
  drawings: Record<string, unknown>,
): Promise<PlacementResult> {
  console.debug("[placement] requesting placement...");
  const res = await fetch("/api/placement", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      space_data_serialized: spaceData,
      brand_data: brandData,
      scale_mm_per_px: scaleMmPerPx,
      drawings_json: drawings,
    }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail ?? `배치 실패: ${res.status}`);
  }
  const result = await res.json();
  console.debug("[placement] done:", result.placed?.length, "placed");
  return result;
}
