/**
 * GLB 파일 로드 (바닥/벽) + InstancedMesh 오브젝트 렌더링.
 *
 * C-4: geometry_id별 그룹화 → InstancedMesh 1개/그룹.
 * GLB는 바닥+벽만 사용. 오브젝트는 placed 데이터로 직접 생성.
 */
import { useRef, useEffect } from "react";
import * as THREE from "three";
// @ts-ignore — three/examples types may be missing
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader";
import type { PlacedObject, FloorViz } from "../../api/placement";


export function meshColor(name: string): THREE.Color {
  if (name.includes("floor")) return new THREE.Color(0xf0f0f0);
  if (name.includes("wall"))  return new THREE.Color(0xcccccc);
  if (name.includes("character") || name.includes("photo")) return new THREE.Color(0x4caf50);
  if (name.includes("shelf")) return new THREE.Color(0xff9800);
  if (name.includes("display") || name.includes("table")) return new THREE.Color(0x2196f3);
  if (name.includes("banner")) return new THREE.Color(0x9c27b0);
  return new THREE.Color(0x888888);
}

const ZONE_COLORS: Record<string, number> = {
  entrance_zone: 0x4caf50,
  mid_zone:      0xff9800,
  deep_zone:     0x2196f3,
  unknown:       0x9e9e9e,
};

const CYLINDER_KEYWORDS = ["cylinder", "round", "column", "pillar"];

function isCylinder(category: string | undefined): boolean {
  if (!category) return false;
  const lower = category.toLowerCase();
  return CYLINDER_KEYWORDS.some(kw => lower.includes(kw));
}

/** geometry_id → { geometry, objects[] } 그룹화 */
interface GeoGroup {
  geometry: THREE.BufferGeometry;
  objects: PlacedObject[];
}

function groupByGeometryId(placed: PlacedObject[]): Map<string, GeoGroup> {
  const groups = new Map<string, GeoGroup>();

  for (const obj of placed) {
    const gid = obj.geometry_id;
    if (!gid) continue;

    if (!groups.has(gid)) {
      // geometry 1회 생성
      const w = obj.width_mm;
      const d = Math.max(obj.depth_mm, 20); // MIN_DEPTH_MM
      const h = obj.height_mm || 1000;

      let geometry: THREE.BufferGeometry;
      if (isCylinder(obj.category)) {
        const diameter = Math.max(w, d);
        geometry = new THREE.CylinderGeometry(diameter / 2, diameter / 2, h, 32);
      } else {
        geometry = new THREE.BoxGeometry(w, h, d);
      }

      groups.set(gid, { geometry, objects: [] });
    }

    groups.get(gid)!.objects.push(obj);
  }

  return groups;
}


export function useGLBScene(glbBase64: string, placed?: PlacedObject[], floorViz?: FloorViz) {
  const groupRef = useRef<THREE.Group>(null);
  const objectMeshes = useRef<THREE.Mesh[]>([]);
  const instancedRef = useRef<THREE.InstancedMesh[]>([]);
  const vizRef = useRef<THREE.Object3D[]>([]);

  useEffect(() => {
    if (!glbBase64 || !groupRef.current) return;

    const binary = atob(glbBase64);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);

    const loader = new GLTFLoader();
    loader.parse(bytes.buffer, "", (gltf: any) => {
      if (!groupRef.current) return;

      // 기존 자식 클린업
      _cleanGroup(groupRef.current);

      // placed + geometry_id 있으면 InstancedMesh 모드, 없으면 GLB 원본 유지
      const useInstancing = placed && placed.length > 0 && placed.some(p => p.geometry_id);

      gltf.scene.traverse((child: any) => {
        if (child instanceof THREE.Mesh) {
          const name = child.name || child.parent?.name || "";
          const isFloor = name.includes("floor");
          const isWall = name.includes("wall");
          const isObj = name.startsWith("obj_");

          if (child.geometry.attributes.color)
            child.geometry.deleteAttribute("color");

          if (isFloor || isWall) {
            child.material = new THREE.MeshBasicMaterial({
              color: isFloor ? 0xf0f0f0 : 0xcccccc,
              transparent: isWall,
              opacity: isWall ? 0.4 : 1.0,
            });
          } else if (isObj && !useInstancing) {
            // InstancedMesh 미사용 시 GLB 원본 오브젝트 유지
            const color = meshColor(name);
            child.material = new THREE.MeshBasicMaterial({ color });
            child.userData.objectType = name;
            child.userData.originalColor = color.getHex();
          }
        }
      });

      if (useInstancing) {
        // InstancedMesh 모드: GLB에서 오브젝트 제거
        const sceneClone = gltf.scene.clone(true);
        _removeObjectMeshes(sceneClone);
        groupRef.current.add(sceneClone);
      } else {
        // GLB 원본 모드: 오브젝트 포함 전체 추가
        groupRef.current.add(gltf.scene);
      }

      // InstancedMesh 생성 (placed 데이터 기반)
      const meshes: THREE.Mesh[] = [];
      const instanced: THREE.InstancedMesh[] = [];

      if (useInstancing) {
        const geoGroups = groupByGeometryId(placed);
        console.debug(`[GLBScene] ${geoGroups.size} unique geometries, ${placed.length} instances`);

        for (const [gid, group] of geoGroups) {
          const count = group.objects.length;

          // zone별 색상 → 인스턴스별 color attribute
          const material = new THREE.MeshBasicMaterial({ vertexColors: false });
          const iMesh = new THREE.InstancedMesh(group.geometry, material, count);
          iMesh.instanceMatrix.setUsage(THREE.DynamicDrawUsage);

          // 인스턴스별 색상
          const colors = new Float32Array(count * 3);
          const tmpColor = new THREE.Color();

          const matrix = new THREE.Matrix4();
          const position = new THREE.Vector3();
          const quaternion = new THREE.Quaternion();
          const scale = new THREE.Vector3(1, 1, 1);

          for (let i = 0; i < count; i++) {
            const obj = group.objects[i];
            const h = obj.height_mm || 1000;

            // Y-up 좌표계: (center_x_mm, h/2, center_y_mm)
            position.set(obj.center_x_mm, h / 2, obj.center_y_mm);

            // Y축 회전 (top-view, 부호 반전 = GLB exporter와 동일)
            const radY = -obj.rotation_deg * (Math.PI / 180);
            quaternion.setFromAxisAngle(new THREE.Vector3(0, 1, 0), radY);

            matrix.compose(position, quaternion, scale);
            iMesh.setMatrixAt(i, matrix);

            // zone 색상
            const zoneColor = ZONE_COLORS[obj.zone_label] ?? ZONE_COLORS.unknown;
            tmpColor.setHex(zoneColor);
            colors[i * 3] = tmpColor.r;
            colors[i * 3 + 1] = tmpColor.g;
            colors[i * 3 + 2] = tmpColor.b;
          }

          // instanceColor 설정
          iMesh.instanceColor = new THREE.InstancedBufferAttribute(colors, 3);
          iMesh.instanceMatrix.needsUpdate = true;

          iMesh.userData.geometryId = gid;
          iMesh.userData.objects = group.objects;
          iMesh.name = `instanced_${gid.slice(0, 8)}`;

          groupRef.current!.add(iMesh);
          instanced.push(iMesh);

          // Raycast용: 각 인스턴스를 개별 Mesh로도 등록
          for (let i = 0; i < count; i++) {
            const obj = group.objects[i];
            const proxy = new THREE.Mesh(group.geometry);
            proxy.visible = false;
            proxy.userData.objectType = `obj_${i}_${obj.object_type}`;
            proxy.userData.originalColor = ZONE_COLORS[obj.zone_label] ?? ZONE_COLORS.unknown;
            proxy.userData.instanceIndex = i;
            proxy.userData.instancedMesh = iMesh;
            proxy.userData.placedObject = obj;

            const h = obj.height_mm || 1000;
            proxy.position.set(obj.center_x_mm, h / 2, obj.center_y_mm);
            const radY = -obj.rotation_deg * (Math.PI / 180);
            proxy.quaternion.setFromAxisAngle(new THREE.Vector3(0, 1, 0), radY);
            proxy.updateMatrixWorld(true);

            groupRef.current!.add(proxy);
            meshes.push(proxy);
          }
        }
      }

      // ── 3D 바닥 동선 시각화 (mm 단위, Y-up) ─────────────────────────
      const vizObjects: THREE.Object3D[] = [];

      if (floorViz && floorViz.slots && floorViz.slots.length > 0) {
        const vizGroup = new THREE.Group();
        vizGroup.name = "floor_viz_group";

        const maxWalk = floorViz.max_walk_mm || 1;
        // ZONE_COLORS 재사용 (모듈 레벨 상수)

        // 공유 geometry (32 세그먼트, XZ 평면에 눕힘)
        const discGeo = new THREE.CircleGeometry(400, 32);
        discGeo.rotateX(-Math.PI / 2);

        for (const slot of floorViz.slots) {
          const color = ZONE_COLORS[slot.zone_label] ?? 0x999999;
          const walkRatio = slot.walk_mm / maxWalk;
          const opacity = 0.15 + (1 - walkRatio) * 0.25;

          const mat = new THREE.MeshBasicMaterial({
            color,
            transparent: true,
            opacity,
            depthWrite: false,
            depthTest: false,  // 바닥 메시와 Z-fighting 방지
            side: THREE.DoubleSide,
          });

          const disc = new THREE.Mesh(discGeo, mat);
          // mm 단위 그대로, Y=6mm (바닥 상면 Y=5 바로 위)
          disc.position.set(slot.x_mm, 6, slot.y_mm);
          disc.renderOrder = 999;  // 바닥/벽보다 나중에 렌더링
          vizGroup.add(disc);
        }

        // Main Artery — Spline Road (CatmullRom + Ribbon Mesh)
        if (floorViz.main_artery && floorViz.main_artery.length >= 2) {
          const ROAD_Y = 6;        // 바닥 상면(Y=5) 바로 위 — logarithmicDepthBuffer로 정밀도 확보
          const ROAD_WIDTH = 800;  // 폭 800mm

          // 원본 노드 → CatmullRomCurve3 부드러운 곡선
          const controlPoints = floorViz.main_artery.map(
            ([x, y]) => new THREE.Vector3(x, ROAD_Y, y)
          );
          const curve = new THREE.CatmullRomCurve3(controlPoints, false, "centripetal", 0.5);
          const SEGMENTS = Math.max(40, floorViz.main_artery.length * 8);
          const curvePoints = curve.getPoints(SEGMENTS);

          // Y 고정: 모든 보간점을 ROAD_Y에 밀착
          for (const pt of curvePoints) {
            pt.y = ROAD_Y;
          }

          // Ribbon Mesh: 곡선을 따라 폭 800mm 평면 메시 생성
          const positions: number[] = [];
          const indices: number[] = [];
          const uvs: number[] = [];

          for (let i = 0; i < curvePoints.length; i++) {
            const p = curvePoints[i];
            // 접선 벡터 → 수직(좌우) 방향 계산
            let tangent: THREE.Vector3;
            if (i < curvePoints.length - 1) {
              tangent = new THREE.Vector3().subVectors(curvePoints[i + 1], p).normalize();
            } else {
              tangent = new THREE.Vector3().subVectors(p, curvePoints[i - 1]).normalize();
            }
            // Y-up 평면에서 좌우 방향 = tangent × Y축
            const right = new THREE.Vector3().crossVectors(tangent, new THREE.Vector3(0, 1, 0)).normalize();
            const halfW = ROAD_WIDTH / 2;

            // 좌우 두 점 — Y는 ROAD_Y 고정
            positions.push(p.x - right.x * halfW, ROAD_Y, p.z - right.z * halfW);
            positions.push(p.x + right.x * halfW, ROAD_Y, p.z + right.z * halfW);

            const t = i / (curvePoints.length - 1);
            uvs.push(0, t);
            uvs.push(1, t);

            if (i < curvePoints.length - 1) {
              const base = i * 2;
              indices.push(base, base + 1, base + 2);
              indices.push(base + 1, base + 3, base + 2);
            }
          }

          const ribbonGeo = new THREE.BufferGeometry();
          ribbonGeo.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
          ribbonGeo.setAttribute("uv", new THREE.Float32BufferAttribute(uvs, 2));
          ribbonGeo.setIndex(indices);
          ribbonGeo.computeVertexNormals();

          const ribbonMat = new THREE.MeshBasicMaterial({
            color: 0xe91e63,
            transparent: true,
            opacity: 0.4,
            depthWrite: false,
            depthTest: true,
            polygonOffset: true,
            polygonOffsetFactor: -2,
            polygonOffsetUnits: -2,
            side: THREE.DoubleSide,
          });

          const ribbon = new THREE.Mesh(ribbonGeo, ribbonMat);
          vizGroup.add(ribbon);

          // 곡선 중심선 (얇은 라인으로 보조)
          const clampedPoints = curvePoints.map(p => new THREE.Vector3(p.x, ROAD_Y + 1, p.z));
          const centerLineGeo = new THREE.BufferGeometry().setFromPoints(clampedPoints);
          const centerLineMat = new THREE.LineBasicMaterial({
            color: 0xffffff,
            transparent: true,
            opacity: 0.5,
            depthWrite: false,
            depthTest: true,
          });
          const centerLine = new THREE.Line(centerLineGeo, centerLineMat);
          vizGroup.add(centerLine);

          // 유입 동선 화살표: 백엔드 raw 노드 기준 (보간 아닌 원본 좌표)
          const rawPts = floorViz.main_artery;
          if (rawPts.length >= 2) {
            const rawEnd = new THREE.Vector3(rawPts[rawPts.length - 1][0], ROAD_Y + 3, rawPts[rawPts.length - 1][1]);
            const rawPrev = new THREE.Vector3(rawPts[rawPts.length - 2][0], ROAD_Y + 3, rawPts[rawPts.length - 2][1]);
            const dir = new THREE.Vector3().subVectors(rawEnd, rawPrev).normalize();
            const arrowLen = Math.min(1200, maxWalk * 0.1);
            const arrowOrigin = rawEnd.clone().sub(dir.clone().multiplyScalar(arrowLen));
            const arrow = new THREE.ArrowHelper(
              dir, arrowOrigin, arrowLen,
              0xe91e63, arrowLen * 0.3, arrowLen * 0.15
            );
            vizGroup.add(arrow);
          }
        }

        // Sub-path (부동선) — 얇은 복귀 루프
        if (floorViz.sub_path && floorViz.sub_path.length >= 2) {
          const SUB_Y = 7;
          const subPoints = floorViz.sub_path.map(
            ([x, y]) => new THREE.Vector3(x, SUB_Y, y)
          );
          const subCurve = new THREE.CatmullRomCurve3(subPoints, false, "centripetal", 0.3);
          const subCurvePoints = subCurve.getPoints(Math.max(30, floorViz.sub_path.length * 4));

          const subLineGeo = new THREE.BufferGeometry().setFromPoints(subCurvePoints);
          const subLineMat = new THREE.LineBasicMaterial({
            color: 0x66bb6a,      // 녹색 — 주동선(핑크)과 구분
            transparent: true,
            opacity: 0.6,
            depthWrite: false,
            depthTest: true,
          });
          const subLine = new THREE.Line(subLineGeo, subLineMat);
          vizGroup.add(subLine);

          console.debug(`[GLBScene] sub_path: ${floorViz.sub_path.length} nodes`);
        }

        // 입구 마커 — 바닥 밀착 2D 화살표 (Decal)
        if (floorViz.entrances && floorViz.entrances.length > 0) {
          const DECAL_Y = 6;
          for (const [ex, ey] of floorViz.entrances) {
            // 바닥 밀착 원형 링 (두께 없음)
            const ringGeo = new THREE.RingGeometry(400, 600, 32);
            ringGeo.rotateX(-Math.PI / 2);
            const ringMat = new THREE.MeshBasicMaterial({
              color: 0x00e676,
              transparent: true,
              opacity: 0.6,
              depthWrite: false,
              depthTest: true,
              side: THREE.DoubleSide,
            });
            const ring = new THREE.Mesh(ringGeo, ringMat);
            ring.position.set(ex, DECAL_Y, ey);
            vizGroup.add(ring);

            // "ENTRANCE" 텍스트 대신 얇은 십자선
            const crossSize = 300;
            const crossGeo = new THREE.BufferGeometry().setFromPoints([
              new THREE.Vector3(ex - crossSize, DECAL_Y + 1, ey),
              new THREE.Vector3(ex + crossSize, DECAL_Y + 1, ey),
              new THREE.Vector3(ex, DECAL_Y + 1, ey - crossSize),
              new THREE.Vector3(ex, DECAL_Y + 1, ey + crossSize),
            ]);
            const crossMat = new THREE.LineBasicMaterial({
              color: 0x00e676,
              transparent: true,
              opacity: 0.8,
              depthWrite: false,
            });
            const cross = new THREE.LineSegments(crossGeo, crossMat);
            vizGroup.add(cross);
          }
          console.debug(`[GLBScene] entrances: ${floorViz.entrances.length} decals`);
        }

        groupRef.current!.add(vizGroup);
        vizObjects.push(vizGroup);

        console.debug(`[GLBScene] floor viz: ${floorViz.slots.length} zone discs, `
          + `${floorViz.main_artery?.length ?? 0} artery nodes, `
          + `${floorViz.sub_path?.length ?? 0} sub_path nodes`);
      }

      vizRef.current = vizObjects;

      // GLB 원본 모드: gltf.scene에서 오브젝트 메시 수집
      if (!useInstancing) {
        gltf.scene.traverse((child: any) => {
          if (child instanceof THREE.Mesh) {
            const name = child.name || child.parent?.name || "";
            if (name.startsWith("obj_") || (!name.includes("floor") && !name.includes("wall") && child.userData.objectType)) {
              meshes.push(child);
            }
          }
        });
      }

      objectMeshes.current = meshes;
      instancedRef.current = instanced;
      console.log(`[GLBScene] loaded: ${instanced.length} InstancedMesh, ${meshes.length} objects (instancing=${useInstancing})`);

    }, (err: any) => console.error("[GLBScene] parse error:", err));

    return () => {
      if (groupRef.current) _cleanGroup(groupRef.current);
      objectMeshes.current = [];
      // InstancedMesh geometry/material dispose
      for (const im of instancedRef.current) {
        im.geometry.dispose();
        if (im.material instanceof THREE.Material) im.material.dispose();
      }
      instancedRef.current = [];
      // floor viz dispose (재귀 순회)
      for (const obj of vizRef.current) {
        _disposeObject(obj);
      }
      vizRef.current = [];
    };
  }, [glbBase64, placed, floorViz]);

  return { groupRef, objectMeshes, instancedRef };
}


/** GLB scene에서 obj_ 이름의 오브젝트 메시 제거 */
function _removeObjectMeshes(scene: THREE.Object3D) {
  const toRemove: THREE.Object3D[] = [];
  scene.traverse((child) => {
    const name = child.name || "";
    if (name.startsWith("obj_")) {
      toRemove.push(child);
    }
  });
  for (const obj of toRemove) {
    obj.removeFromParent();
    _disposeObject(obj);
  }
}


function _cleanGroup(group: THREE.Group) {
  while (group.children.length > 0) {
    const child = group.children[0];
    _disposeObject(child);
    group.remove(child);
  }
}


function _disposeObject(obj: THREE.Object3D) {
  obj.traverse((child) => {
    if (child instanceof THREE.Mesh) {
      child.geometry?.dispose();
      if (child.material instanceof THREE.Material) {
        child.material.dispose();
      } else if (Array.isArray(child.material)) {
        child.material.forEach(m => m.dispose());
      }
    }
    if (child instanceof THREE.InstancedMesh) {
      child.geometry?.dispose();
      if (child.material instanceof THREE.Material) {
        child.material.dispose();
      }
    }
  });
}
