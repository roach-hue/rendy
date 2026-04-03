import { Canvas, useThree, useFrame } from "@react-three/fiber";
import { OrbitControls, GizmoHelper, GizmoViewport } from "@react-three/drei";
import { useRef, useEffect, useState, useCallback } from "react";
import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader";

type InteractMode = "orbit" | "drag" | "rotate";

interface SceneViewerProps {
  glbBase64: string;
  onObjectMove?: (objectType: string, x: number, z: number, rotDeg: number) => void;
}

export function SceneViewer({ glbBase64, onObjectMove }: SceneViewerProps) {
  const [mode, setMode] = useState<InteractMode>("orbit");

  return (
    <div>
      {/* 모드 토글 버튼 */}
      <div style={styles.toolbar}>
        {(["orbit", "drag", "rotate"] as const).map(m => (
          <button
            key={m}
            onClick={() => setMode(m)}
            style={{
              ...styles.modeBtn,
              background: mode === m ? "#1a1a1a" : "#fff",
              color: mode === m ? "#fff" : "#333",
            }}
          >
            {m === "orbit" ? "카메라 회전" : m === "drag" ? "오브젝트 이동" : "오브젝트 회전"}
          </button>
        ))}
      </div>

      <div style={{ width: "100%", height: "600px", background: "#e8e8e8", borderRadius: 8 }}>
        <Canvas
          camera={{ position: [10000, 10000, 15000], fov: 50, near: 1, far: 100000 }}
          gl={{ antialias: true }}
        >
          <ambientLight intensity={1.5} />
          <directionalLight position={[10, 20, 10]} intensity={2} />
          <directionalLight position={[-10, 15, -5]} intensity={1} />
          <hemisphereLight args={["#ffffff", "#666666", 1.0]} />

          <GLBScene glbBase64={glbBase64} mode={mode} onObjectMove={onObjectMove} />
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

// ── GLB 로드 + 인터랙션 ─────────────────────────────────────────────────────

interface GLBSceneProps {
  glbBase64: string;
  mode: InteractMode;
  onObjectMove?: (objectType: string, x: number, z: number, rotDeg: number) => void;
}

function GLBScene({ glbBase64, mode, onObjectMove }: GLBSceneProps) {
  const groupRef = useRef<THREE.Group>(null);
  const { camera, gl, raycaster } = useThree();

  // 오브젝트 메시 리스트 (floor/wall 제외)
  const objectMeshes = useRef<THREE.Mesh[]>([]);
  // 드래그/회전 상태
  const activeObj = useRef<THREE.Mesh | null>(null);
  const dragStart = useRef<THREE.Vector3 | null>(null);
  const rotateStartX = useRef<number>(0);
  const rotateStartAngle = useRef<number>(0);

  // XZ 평면 (Y=0)
  const xzPlane = useRef(new THREE.Plane(new THREE.Vector3(0, 1, 0), 0));

  // ── GLB 로드 ──────────────────────────────────────────────────────────────
  useEffect(() => {
    if (!glbBase64 || !groupRef.current) return;

    const binary = atob(glbBase64);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);

    const loader = new GLTFLoader();
    loader.parse(bytes.buffer, "", (gltf) => {
      if (!groupRef.current) return;
      while (groupRef.current.children.length > 0)
        groupRef.current.remove(groupRef.current.children[0]);

      const meshes: THREE.Mesh[] = [];

      gltf.scene.traverse((child) => {
        if (child instanceof THREE.Mesh) {
          const name = child.name || child.parent?.name || "";

          if (child.geometry.attributes.color)
            child.geometry.deleteAttribute("color");

          const color = _meshColor(name);
          const isWall = name.includes("wall");
          child.material = new THREE.MeshBasicMaterial({
            color,
            transparent: isWall,
            opacity: isWall ? 0.4 : 1.0,
          });

          // floor/wall 아닌 오브젝트만 인터랙션 대상
          if (!name.includes("floor") && !isWall) {
            child.userData.objectType = name;
            child.userData.originalColor = color.getHex();
            meshes.push(child);
          }
        }
      });

      objectMeshes.current = meshes;
      groupRef.current.add(gltf.scene);
      console.log("[SceneViewer] loaded:", meshes.length, "interactive objects");
    }, (err) => console.error("[SceneViewer] parse error:", err));
  }, [glbBase64]);

  // ── Raycast → XZ 평면 교차점 ──────────────────────────────────────────────
  const getXZIntersect = useCallback((e: PointerEvent): THREE.Vector3 | null => {
    const rect = gl.domElement.getBoundingClientRect();
    const mouse = new THREE.Vector2(
      ((e.clientX - rect.left) / rect.width) * 2 - 1,
      -((e.clientY - rect.top) / rect.height) * 2 + 1,
    );
    raycaster.setFromCamera(mouse, camera);
    const target = new THREE.Vector3();
    const hit = raycaster.ray.intersectPlane(xzPlane.current, target);
    return hit ? target : null;
  }, [camera, gl, raycaster]);

  // ── Raycast → 오브젝트 히트 ───────────────────────────────────────────────
  const getHitObject = useCallback((e: PointerEvent): THREE.Mesh | null => {
    const rect = gl.domElement.getBoundingClientRect();
    const mouse = new THREE.Vector2(
      ((e.clientX - rect.left) / rect.width) * 2 - 1,
      -((e.clientY - rect.top) / rect.height) * 2 + 1,
    );
    raycaster.setFromCamera(mouse, camera);
    const hits = raycaster.intersectObjects(objectMeshes.current, true);
    if (hits.length > 0) {
      let obj = hits[0].object as THREE.Mesh;
      // parent가 interactive object일 수 있음
      while (obj && !obj.userData.objectType && obj.parent) {
        obj = obj.parent as THREE.Mesh;
      }
      return obj.userData.objectType ? obj : null;
    }
    return null;
  }, [camera, gl, raycaster]);

  // ── 포인터 이벤트 ─────────────────────────────────────────────────────────
  useEffect(() => {
    if (mode === "orbit") return;
    const dom = gl.domElement;

    function onPointerDown(e: PointerEvent) {
      if (mode === "drag") {
        const obj = getHitObject(e);
        if (!obj) return;
        activeObj.current = obj;
        dragStart.current = getXZIntersect(e);
        _highlight(obj, true);
        dom.style.cursor = "grabbing";
      } else if (mode === "rotate") {
        const obj = getHitObject(e);
        if (!obj) return;
        activeObj.current = obj;
        rotateStartX.current = e.clientX;
        rotateStartAngle.current = obj.rotation.y;
        _highlight(obj, true);
        dom.style.cursor = "ew-resize";
      }
    }

    function onPointerMove(e: PointerEvent) {
      if (!activeObj.current) {
        // hover 커서
        const obj = getHitObject(e);
        dom.style.cursor = obj ? (mode === "drag" ? "grab" : "ew-resize") : "default";
        return;
      }

      if (mode === "drag" && dragStart.current) {
        const current = getXZIntersect(e);
        if (!current) return;
        const delta = current.clone().sub(dragStart.current);
        activeObj.current.position.add(delta);
        dragStart.current = current;
      } else if (mode === "rotate") {
        const deltaX = e.clientX - rotateStartX.current;
        const delta = deltaX * 0.01 - (activeObj.current.rotation.y - rotateStartAngle.current);
        // 오브젝트 바운딩박스 중심을 pivot으로 제자리 Y축 회전
        const obj = activeObj.current;
        const box = new THREE.Box3().setFromObject(obj);
        const center = box.getCenter(new THREE.Vector3());
        obj.position.sub(center);
        obj.position.applyAxisAngle(new THREE.Vector3(0, 1, 0), delta);
        obj.position.add(center);
        obj.rotateOnWorldAxis(new THREE.Vector3(0, 1, 0), delta);
      }
    }

    function onPointerUp() {
      if (activeObj.current) {
        const obj = activeObj.current;
        _highlight(obj, false);
        // 콜백
        if (onObjectMove) {
          onObjectMove(
            obj.userData.objectType,
            obj.position.x,
            obj.position.z,
            THREE.MathUtils.radToDeg(obj.rotation.y),
          );
        }
        console.debug("[SceneViewer]", mode, obj.userData.objectType,
          `pos=(${obj.position.x.toFixed(0)}, ${obj.position.z.toFixed(0)})`,
          `rot=${THREE.MathUtils.radToDeg(obj.rotation.y).toFixed(1)}°`);
        activeObj.current = null;
        dragStart.current = null;
        dom.style.cursor = "default";
      }
    }

    dom.addEventListener("pointerdown", onPointerDown);
    dom.addEventListener("pointermove", onPointerMove);
    dom.addEventListener("pointerup", onPointerUp);

    return () => {
      dom.removeEventListener("pointerdown", onPointerDown);
      dom.removeEventListener("pointermove", onPointerMove);
      dom.removeEventListener("pointerup", onPointerUp);
      dom.style.cursor = "default";
    };
  }, [mode, gl, getHitObject, getXZIntersect, onObjectMove]);

  return <group ref={groupRef} />;
}

// ── 하이라이트 ──────────────────────────────────────────────────────────────

function _highlight(mesh: THREE.Mesh, on: boolean) {
  if (mesh.material instanceof THREE.MeshBasicMaterial) {
    if (on) {
      mesh.material.color.set(0xffff00);
    } else {
      mesh.material.color.setHex(mesh.userData.originalColor ?? 0x888888);
    }
  }
}

// ── 색상 ────────────────────────────────────────────────────────────────────

function _meshColor(name: string): THREE.Color {
  if (name.includes("floor")) return new THREE.Color(0xf0f0f0);
  if (name.includes("wall"))  return new THREE.Color(0xcccccc);
  if (name.includes("character") || name.includes("photo")) return new THREE.Color(0x4caf50);
  if (name.includes("shelf")) return new THREE.Color(0xff9800);
  if (name.includes("display") || name.includes("table")) return new THREE.Color(0x2196f3);
  if (name.includes("banner")) return new THREE.Color(0x9c27b0);
  return new THREE.Color(0x888888);
}

// ── 스타일 ──────────────────────────────────────────────────────────────────

const styles: Record<string, React.CSSProperties> = {
  toolbar: { display: "flex", gap: 8, marginBottom: 8 },
  modeBtn: {
    padding: "6px 14px", fontSize: 13, fontWeight: 600,
    border: "1px solid #ccc", borderRadius: 6, cursor: "pointer",
  },
};
