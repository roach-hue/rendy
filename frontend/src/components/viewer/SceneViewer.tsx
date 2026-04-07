/**
 * SceneViewer — 순수 View 계층.
 * Canvas + 조명 + UI 렌더링만. 3D 로직은 Hook에서 주입.
 */
import { Canvas } from "@react-three/fiber";
import { OrbitControls, GizmoHelper, GizmoViewport, Html } from "@react-three/drei";
import { useState } from "react";
import { useGLBScene } from "./useGLBScene";
import { useSceneInteraction } from "./useSceneInteraction";
import type { PlacedObject, FloorViz } from "../../api/placement";

function formatLabel(objectType: string): string {
  return objectType
    .split("_")
    .map(w => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

type InteractMode = "orbit" | "drag" | "rotate";

interface SceneViewerProps {
  glbBase64: string;
  placed?: PlacedObject[];
  floorViz?: FloorViz;
  onObjectMove?: (objectType: string, x: number, z: number, rotDeg: number) => void;
}

export function SceneViewer({ glbBase64, placed, floorViz, onObjectMove }: SceneViewerProps) {
  const [mode, setMode] = useState<InteractMode>("orbit");
  const [showLabels, setShowLabels] = useState(true);

  return (
    <div>
      {/* 모드 토글 */}
      <div style={styles.toolbar}>
        {(["orbit", "drag", "rotate"] as const).map(m => (
          <button key={m} onClick={() => setMode(m)} style={{
            ...styles.modeBtn,
            background: mode === m ? "#1a1a1a" : "#fff",
            color: mode === m ? "#fff" : "#333",
          }}>
            {m === "orbit" ? "카메라 회전" : m === "drag" ? "오브젝트 이동" : "오브젝트 회전"}
          </button>
        ))}
        <button onClick={() => setShowLabels(v => !v)} style={{
          ...styles.modeBtn,
          background: showLabels ? "#1a1a1a" : "#fff",
          color: showLabels ? "#fff" : "#333",
        }}>
          Labels {showLabels ? "ON" : "OFF"}
        </button>
      </div>

      {/* 3D Canvas */}
      <div style={{ width: "100%", height: "600px", background: "#e8e8e8", borderRadius: 8 }}>
        <Canvas camera={{ position: [10000, 10000, 15000], fov: 50, near: 10, far: 100000 }} gl={{ antialias: true, logarithmicDepthBuffer: true }}>
          <ambientLight intensity={1.5} />
          <directionalLight position={[10, 20, 10]} intensity={2} />
          <directionalLight position={[-10, 15, -5]} intensity={1} />
          <hemisphereLight args={["#ffffff", "#666666", 1.0]} />

          <GLBSceneWrapper glbBase64={glbBase64} placed={placed} floorViz={floorViz} mode={mode} onObjectMove={onObjectMove} showLabels={showLabels} />
          <OrbitControls target={[5000, 0, 4000]} enabled={mode === "orbit"} />
          <gridHelper args={[30000, 30, "#bbb", "#ddd"]} />
          <GizmoHelper alignment="bottom-right" margin={[60, 60]}>
            <GizmoViewport labelColor="white" axisHeadScale={1} />
          </GizmoHelper>
        </Canvas>
      </div>
    </div>
  );
}

/**
 * Canvas 내부 컴포넌트 — Hook은 Canvas 안에서만 호출 가능.
 */
function GLBSceneWrapper({ glbBase64, placed, floorViz, mode, onObjectMove, showLabels }: {
  glbBase64: string; placed?: PlacedObject[]; floorViz?: FloorViz; mode: InteractMode;
  onObjectMove?: (objectType: string, x: number, z: number, rotDeg: number) => void;
  showLabels: boolean;
}) {
  const { groupRef, objectMeshes } = useGLBScene(glbBase64, placed, floorViz);
  useSceneInteraction({ mode, objectMeshes, onObjectMove });
  return (
    <group ref={groupRef}>
      {showLabels && placed?.map((obj, i) => (
        <Html
          key={`label-${i}`}
          position={[obj.center_x_mm, (obj.height_mm || 1000) + 200, obj.center_y_mm]}
          center
          style={{ pointerEvents: "none" }}
        >
          <div style={{
            background: "rgba(0,0,0,0.7)",
            color: "#fff",
            fontSize: 11,
            fontWeight: 600,
            padding: "2px 6px",
            borderRadius: 4,
            whiteSpace: "nowrap",
            fontFamily: "monospace",
          }}>
            {formatLabel(obj.object_type)}
          </div>
        </Html>
      ))}
    </group>
  );
}

const styles: Record<string, React.CSSProperties> = {
  toolbar: { display: "flex", gap: 8, marginBottom: 8 },
  modeBtn: { padding: "6px 14px", fontSize: 13, fontWeight: 600, border: "1px solid #ccc", borderRadius: 6, cursor: "pointer" },
};
