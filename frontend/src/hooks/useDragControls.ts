import { useEffect, useRef } from "react";
import * as THREE from "three";
import { DragControls } from "three/addons/controls/DragControls.js";
import { saveObjectPosition } from "../api/layout";

interface UseDragControlsOptions {
  layoutId: string;
  camera: THREE.Camera;
  renderer: THREE.WebGLRenderer;
  objects: THREE.Object3D[];
}

export function useDragControls({
  layoutId,
  camera,
  renderer,
  objects,
}: UseDragControlsOptions) {
  const controlsRef = useRef<DragControls | null>(null);

  useEffect(() => {
    if (!objects.length) return;

    const controls = new DragControls(objects, camera, renderer.domElement);
    controlsRef.current = controls;

    // 드래그 중: 로컬 렌더링만 — API 호출 없음
    const onDrag = () => {
      renderer.render(renderer.info.render as unknown as THREE.Scene, camera);
    };

    // 드래그 완료: 최종 위치 한 번만 저장
    const onDragEnd = (event: THREE.Event & { object: THREE.Object3D }) => {
      const obj = event.object;
      const objectType = obj.userData.object_type as string;

      if (!objectType) {
        console.warn("dragend: object_type 없음 — userData.object_type 확인 필요");
        return;
      }

      // Three.js 좌표 → mm 변환
      // Three.js: x=좌우, y=높이(위), z=앞뒤
      // space_data: x_mm=좌우, y_mm=앞뒤 (높이 제외 — 배치는 바닥 기준)
      saveObjectPosition(layoutId, {
        object_type: objectType,
        x_mm: obj.position.x,
        y_mm: obj.position.z,
        rotation_deg: obj.rotation.y * (180 / Math.PI),
      }).catch((err) => {
        console.error("위치 저장 실패:", err);
        // TODO: 사용자에게 저장 실패 토스트 알림
      });
    };

    controls.addEventListener("drag", onDrag);
    controls.addEventListener("dragend", onDragEnd);

    return () => {
      controls.removeEventListener("drag", onDrag);
      controls.removeEventListener("dragend", onDragEnd);
      controls.dispose();
    };
  }, [layoutId, camera, renderer, objects]);

  return controlsRef;
}
