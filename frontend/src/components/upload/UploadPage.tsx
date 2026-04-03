import { useState } from "react";
import { detectFloorPlan, extractBrand, ParsedDrawings } from "../../api/detect";

interface UploadPageProps {
  onComplete: (drawings: ParsedDrawings, brandData: Record<string, unknown>, floorFile: File) => void;
}

export function UploadPage({ onComplete }: UploadPageProps) {
  const [floorFile, setFloorFile] = useState<File | null>(null);
  const [sectionFile, setSectionFile] = useState<File | null>(null);
  const [brandFile, setBrandFile] = useState<File | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit() {
    if (!floorFile || !brandFile) return;
    setLoading(true);
    setError(null);
    try {
      const [drawings, brandData] = await Promise.all([
        detectFloorPlan(floorFile, sectionFile ?? undefined),
        extractBrand(brandFile),
      ]);
      onComplete(drawings, brandData, floorFile);
    } catch (e) {
      setError(e instanceof Error ? e.message : "오류가 발생했습니다.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div style={styles.container}>
      <h2 style={styles.title}>도면 + 브랜드 메뉴얼 업로드</h2>

      <div style={styles.card}>
        <label style={styles.label}>평면도 * (DXF / PDF / PNG · JPG)</label>
        <input type="file" accept=".dxf,.pdf,.png,.jpg,.jpeg"
          onChange={e => setFloorFile(e.target.files?.[0] ?? null)} />

        <label style={styles.label}>단면도 (선택 — ceiling height 추출용)</label>
        <input type="file" accept=".dxf,.pdf,.png,.jpg,.jpeg"
          onChange={e => setSectionFile(e.target.files?.[0] ?? null)} />

        <label style={styles.label}>브랜드 메뉴얼 * (PDF)</label>
        <input type="file" accept=".pdf"
          onChange={e => setBrandFile(e.target.files?.[0] ?? null)} />
      </div>

      {error && <p style={styles.error}>{error}</p>}

      <button
        style={{
          ...styles.button,
          opacity: !floorFile || !brandFile || loading ? 0.5 : 1,
        }}
        disabled={!floorFile || !brandFile || loading}
        onClick={handleSubmit}
      >
        {loading ? "분석 중…" : "분석 시작"}
      </button>
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  container: { maxWidth: 520, margin: "80px auto", padding: "0 24px", fontFamily: "sans-serif" },
  title:     { fontSize: 22, fontWeight: 700, marginBottom: 24 },
  card:      { display: "flex", flexDirection: "column", gap: 16, padding: 24, border: "1px solid #e0e0e0", borderRadius: 8 },
  label:     { fontSize: 14, fontWeight: 600, color: "#333" },
  error:     { color: "#d32f2f", fontSize: 14, marginTop: 8 },
  button:    { marginTop: 24, width: "100%", padding: "14px 0", background: "#1a1a1a", color: "#fff",
               border: "none", borderRadius: 8, fontSize: 16, fontWeight: 600, cursor: "pointer" },
};
