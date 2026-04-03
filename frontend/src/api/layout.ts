const API_BASE = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

export interface ObjectPosition {
  object_type: string;
  x_mm: number;
  y_mm: number;
  rotation_deg: number;
}

export async function saveObjectPosition(
  layoutId: string,
  position: ObjectPosition
): Promise<void> {
  const res = await fetch(
    `${API_BASE}/layout/${layoutId}/object/${position.object_type}`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(position),
    }
  );
  if (!res.ok) {
    throw new Error(`saveObjectPosition 실패: ${res.status}`);
  }
}
