import { useState } from "react";
import { ParsedDrawings } from "./api/detect";
import { runPlacement, PlacementResult } from "./api/placement";
import { UploadPage } from "./components/upload/UploadPage";
import { MarkingPage } from "./components/marking/MarkingPage";
import { ConfirmPage } from "./components/confirm/ConfirmPage";
import { PlacementPage } from "./components/placement/PlacementPage";

type Step = "upload" | "marking" | "confirm" | "placement";

export default function App() {
  const [step, setStep] = useState<Step>("upload");
  const [drawings, setDrawings] = useState<ParsedDrawings | null>(null);
  const [brandData, setBrandData] = useState<Record<string, unknown>>({});
  const [floorFile, setFloorFile] = useState<File | null>(null);
  const [spaceData, setSpaceData] = useState<Record<string, unknown>>({});
  const [scale, setScale] = useState(10);
  const [placementResult, setPlacementResult] = useState<PlacementResult | null>(null);
  const [placementLoading, setPlacementLoading] = useState(false);
  const [placementError, setPlacementError] = useState<string | null>(null);

  // 3단계 확정 시 캐시 저장
  async function saveCache() {
    try {
      await fetch("/api/cache-save", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ space_data: spaceData, brand_data: brandData, scale, drawings }),
      });
      console.debug("[App] cache saved");
    } catch (e) {
      console.error("[App] cache save failed:", e);
    }
  }

  // 캐시 로드 → 바로 4단계
  async function loadCacheAndPlace() {
    try {
      const res = await fetch("/api/cache-load");
      if (!res.ok) { alert("캐시 없음 — 먼저 1~3단계를 진행하세요"); return; }
      const cached = await res.json();
      setSpaceData(cached.space_data || {});
      setBrandData(cached.brand_data || {});
      setScale(cached.scale || 10);
      setDrawings(cached.drawings || null);
      console.debug("[App] cache loaded, starting placement");
      // 바로 배치 실행
      setPlacementLoading(true);
      setPlacementError(null);
      setStep("placement");
      const result = await runPlacement(
        cached.space_data, cached.brand_data, cached.scale,
        cached.drawings as Record<string, unknown>,
      );
      setPlacementResult(result);
    } catch (e) {
      setPlacementError(e instanceof Error ? e.message : "캐시 로드 실패");
    } finally {
      setPlacementLoading(false);
    }
  }

  async function handleConfirmDone() {
    if (!drawings) return;
    await saveCache();
    setPlacementLoading(true);
    setPlacementError(null);
    setStep("placement");

    try {
      const result = await runPlacement(
        spaceData,
        brandData,
        scale,
        drawings as unknown as Record<string, unknown>,
      );
      setPlacementResult(result);
      console.debug("[App] placement complete:", result.placed.length, "placed");
    } catch (e) {
      const msg = e instanceof Error ? e.message : "배치 실패";
      setPlacementError(msg);
      console.error("[App] placement error:", msg);
    } finally {
      setPlacementLoading(false);
    }
  }

  return (
    <div style={{ minHeight: "100vh", background: "#fafafa" }}>
      <StepBar current={step} />

      {step === "upload" && (
        <>
          <UploadPage
            onComplete={(d, b, f) => {
              setDrawings(d);
              setBrandData(b);
              setFloorFile(f);
              setStep("marking");
            }}
          />
          <div style={{ textAlign: "center", marginTop: 16 }}>
            <button
              onClick={loadCacheAndPlace}
              style={{ padding: "10px 24px", background: "#555", color: "#fff",
                border: "none", borderRadius: 6, fontSize: 13, cursor: "pointer" }}
            >
              캐시로 바로 배치 (1~3단계 건너뛰기)
            </button>
          </div>
        </>
      )}

      {step === "marking" && drawings && floorFile && (
        <MarkingPage
          drawings={drawings}
          floorFile={floorFile}
          onComplete={(sd, sc) => {
            setSpaceData(sd);
            setScale(sc);
            setStep("confirm");
          }}
        />
      )}

      {step === "confirm" && (
        <ConfirmPage
          spaceData={spaceData}
          brandData={brandData}
          scale={scale}
          floorFile={floorFile!}
          previewBase64={drawings?.preview_image_base64}
          onConfirm={handleConfirmDone}
        />
      )}

      {step === "placement" && (
        <PlacementPage
          result={placementResult}
          loading={placementLoading}
          error={placementError}
        />
      )}
    </div>
  );
}

function StepBar({ current }: { current: Step }) {
  const steps: { key: Step; label: string }[] = [
    { key: "upload",    label: "1. 업로드" },
    { key: "marking",   label: "2. 감지 확인" },
    { key: "confirm",   label: "3. 검토" },
    { key: "placement", label: "4. 배치" },
  ];
  return (
    <div style={{ display: "flex", justifyContent: "center", gap: 0,
      borderBottom: "1px solid #e0e0e0", background: "#fff", padding: "0 24px" }}>
      {steps.map(({ key, label }) => (
        <div key={key} style={{
          padding: "16px 24px", fontSize: 14, fontWeight: 600,
          color: current === key ? "#1a1a1a" : "#aaa",
          borderBottom: current === key ? "2px solid #1a1a1a" : "2px solid transparent",
        }}>
          {label}
        </div>
      ))}
    </div>
  );
}
