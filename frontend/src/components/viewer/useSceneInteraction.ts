/**
 * 3D 씬 인터랙션 — Raycast, 드래그, 회전, 하이라이트.
 * 클린업: 언마운트 시 포인터 이벤트 제거 + 커서 복원.
 */
import { useRef, useEffect, useCallback } from "react";
import { useThree } from "@react-three/fiber";
import * as THREE from "three";

type InteractMode = "orbit" | "drag" | "rotate";

interface UseSceneInteractionArgs {
  mode: InteractMode;
  objectMeshes: React.RefObject<THREE.Mesh[]>;
  onObjectMove?: (objectType: string, x: number, z: number, rotDeg: number) => void;
}

export function useSceneInteraction({ mode, objectMeshes, onObjectMove }: UseSceneInteractionArgs) {
  const { camera, gl, raycaster } = useThree();

  const activeObj = useRef<THREE.Mesh | null>(null);
  const dragStart = useRef<THREE.Vector3 | null>(null);
  const rotateStartX = useRef(0);
  const rotateStartAngle = useRef(0);
  const xzPlane = useRef(new THREE.Plane(new THREE.Vector3(0, 1, 0), 0));

  const getXZIntersect = useCallback((e: PointerEvent): THREE.Vector3 | null => {
    const rect = gl.domElement.getBoundingClientRect();
    const mouse = new THREE.Vector2(
      ((e.clientX - rect.left) / rect.width) * 2 - 1,
      -((e.clientY - rect.top) / rect.height) * 2 + 1,
    );
    raycaster.setFromCamera(mouse, camera);
    const target = new THREE.Vector3();
    return raycaster.ray.intersectPlane(xzPlane.current, target) ? target : null;
  }, [camera, gl, raycaster]);

  const getHitObject = useCallback((e: PointerEvent): THREE.Mesh | null => {
    const rect = gl.domElement.getBoundingClientRect();
    const mouse = new THREE.Vector2(
      ((e.clientX - rect.left) / rect.width) * 2 - 1,
      -((e.clientY - rect.top) / rect.height) * 2 + 1,
    );
    raycaster.setFromCamera(mouse, camera);
    const meshes = objectMeshes.current;
    if (!meshes) return null;
    const hits = raycaster.intersectObjects(meshes, true);
    if (hits.length > 0) {
      let obj = hits[0].object as THREE.Mesh;
      while (obj && !obj.userData.objectType && obj.parent) obj = obj.parent as THREE.Mesh;
      return obj.userData.objectType ? obj : null;
    }
    return null;
  }, [camera, gl, raycaster, objectMeshes]);

  useEffect(() => {
    if (mode === "orbit") return;
    const dom = gl.domElement;

    function onPointerDown(e: PointerEvent) {
      const obj = getHitObject(e);
      if (!obj) return;
      activeObj.current = obj;
      _highlight(obj, true);

      if (mode === "drag") {
        dragStart.current = getXZIntersect(e);
        dom.style.cursor = "grabbing";
      } else {
        rotateStartX.current = e.clientX;
        rotateStartAngle.current = obj.rotation.y;
        dom.style.cursor = "ew-resize";
      }
    }

    function onPointerMove(e: PointerEvent) {
      if (!activeObj.current) {
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
        if (onObjectMove) {
          onObjectMove(obj.userData.objectType, obj.position.x, obj.position.z,
            THREE.MathUtils.radToDeg(obj.rotation.y));
        }
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
}

function _highlight(mesh: THREE.Mesh, on: boolean) {
  if (mesh.material instanceof THREE.MeshBasicMaterial) {
    mesh.material.color.set(on ? 0xffff00 : (mesh.userData.originalColor ?? 0x888888));
  }
}
