"""
파이프라인 오케스트레이터 — 전체 배치 파이프라인 조율.
Agent 2 → Object Selection → Agent 3 → Placement Engine → Verification → Report → GLB
"""
import base64
import traceback

from app.agents.agent2_back import run as run_agent2
from app.agents.agent3_placement import plan_placement
from app.modules.object_selection import select_eligible_objects
from app.modules.failure_handler import run_with_fallback
from app.modules.verification import verify_placement
from app.modules.report_generator import generate_report
from app.modules.glb_exporter import export_glb
from app.schemas.drawings import ParsedDrawings
from app.schemas.verification import SummaryReport


import hashlib
import json as _json
import time
from pathlib import Path

# 배치 결과 캐시 (동일 도면 → LLM 0회)
_PLACEMENT_CACHE_DIR = Path(__file__).parent.parent.parent / "cache" / "placement"
_PLACEMENT_CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _compute_drawings_hash(drawings_json: dict, scale: float) -> str:
    """도면 + 스케일 해시 → 캐시 키."""
    fp = drawings_json.get("floor_plan", {})
    key = f"{fp.get('floor_polygon_px', [])}:{scale}"
    return hashlib.md5(key.encode()).hexdigest()[:12]


def run_placement_pipeline(
    drawings_json: dict,
    brand_data: dict,
    scale_mm_per_px: float,
) -> dict:
    """
    전체 배치 파이프라인 실행.
    동일 도면(polygon+scale 95% 일치) → 캐시 히트 시 LLM 0회, 0.1초 응답.
    """
    t0 = time.time()
    cache_key = _compute_drawings_hash(drawings_json, scale_mm_per_px)
    cache_file = _PLACEMENT_CACHE_DIR / f"{cache_key}.json"

    # 캐시 히트 → LLM 0회
    if cache_file.exists():
        try:
            cached = _json.loads(cache_file.read_text(encoding="utf-8"))
            elapsed = time.time() - t0
            print(f"[Pipeline] CACHE HIT: {cache_key} → {elapsed:.2f}s (LLM 0회)")
            return cached
        except Exception as e:
            print(f"[Pipeline] cache read failed: {e} — full pipeline")

    print("[Pipeline] placement request received (cache miss)")
    drawings = ParsedDrawings.model_validate(drawings_json)
    sd = run_agent2(drawings=drawings, scale_mm_per_px=scale_mm_per_px)

    eligible = select_eligible_objects(sd, brand_data)
    print(f"[Pipeline] eligible objects: {len(eligible)}")

    placements = plan_placement(eligible, sd, brand_data)
    print(f"[Pipeline] Agent 3 placements: {len(placements)}")

    # GAP: Agent 3이 제안한 기물 중 DB에 없는 것 → furniture_standards에 INSERT
    eligible = _provision_missing_assets(placements, eligible, brand_data)

    result = run_with_fallback(
        placements, eligible, sd, brand_data,
        plan_fn=plan_placement,
    )
    print(f"[Pipeline] placed: {len(result['placed'])}, dropped: {len(result['dropped'])}")

    verification = verify_placement(result["placed"], sd)

    report = generate_report(
        result["placed"], result["dropped"], verification.model_dump(),
        sd, brand_data, result["fallback_used"],
    )

    glb_bytes = export_glb(result["placed"], sd)
    glb_b64 = base64.b64encode(glb_bytes).decode()

    summary = _build_summary(
        sd, result["placed"], result["dropped"],
        result["fallback_used"], verification,
    )

    # 3D 바닥 동선 시각화용 데이터
    # CRITICAL: main_artery 길이 추적
    _artery = sd.get("fire", {}).get("main_artery")
    if _artery and hasattr(_artery, "coords"):
        _ac = list(_artery.coords)
        print(f"[CRITICAL] main_artery BEFORE floor_viz: {len(_ac)} nodes, "
              f"start=({_ac[0][0]:.0f},{_ac[0][1]:.0f}), end=({_ac[-1][0]:.0f},{_ac[-1][1]:.0f})")
    else:
        print(f"[CRITICAL] main_artery BEFORE floor_viz: {type(_artery)} (missing or stripped!)")

    floor_viz = _build_floor_viz(sd, result["placed"])
    print(f"[CRITICAL] floor_viz.main_artery: {len(floor_viz.get('main_artery', []))} nodes, "
          f"sub_path: {len(floor_viz.get('sub_path', []))} nodes")

    from app.api.serializer import strip_shapely
    response = strip_shapely({
        "placed": result["placed"],
        "dropped": result["dropped"],
        "verification": verification.model_dump(),
        "report": report,
        "glb_base64": glb_b64,
        "log": result["log"],
        "summary": summary.model_dump(),
        "floor_viz": floor_viz,
    })

    # 배치 결과 캐시 저장
    try:
        cache_file.write_text(_json.dumps(response, ensure_ascii=False), encoding="utf-8")
        elapsed = time.time() - t0
        print(f"[Pipeline] CACHE SAVE: {cache_key} ({elapsed:.1f}s)")
    except Exception as e:
        print(f"[Pipeline] cache save failed: {e}")

    return response


def run_space_data(drawings: ParsedDrawings, scale: float, entrance_px=None, user_dims=None):
    """Agent 2 후반부 실행 + 직렬화."""
    from app.agents.agent2_back import run

    if user_dims:
        drawings = _rebuild_polygon(drawings, user_dims, scale)

    sd = run(drawings=drawings, scale_mm_per_px=scale, user_entrance_px=entrance_px)

    from app.api.serializer import strip_shapely
    return strip_shapely(sd)


def _rebuild_polygon(drawings, user_dims, scale):
    fp = drawings.floor_plan
    xs = [p[0] for p in fp.floor_polygon_px]
    ys = [p[1] for p in fp.floor_polygon_px]
    cx = (min(xs) + max(xs)) / 2
    cy = (min(ys) + max(ys)) / 2
    half_w = (user_dims["width_mm"] / scale) / 2
    half_h = (user_dims["height_mm"] / scale) / 2

    new_polygon = [
        (cx - half_w, cy - half_h), (cx + half_w, cy - half_h),
        (cx + half_w, cy + half_h), (cx - half_w, cy + half_h),
    ]
    new_fp = fp.model_copy(update={"floor_polygon_px": new_polygon})
    return drawings.model_copy(update={"floor_plan": new_fp})


def _provision_missing_assets(
    placements,
    eligible: list[dict],
    brand_data: dict,
    brand_id: str = "sanrio",
) -> list[dict]:
    """
    Generative Asset Provisioning:
    Agent 3이 제안한 기물 중 eligible에 없는 것을 DB에 INSERT하고 eligible에 추가.
    """
    eligible_types = {o["object_type"] for o in eligible}
    missing = []

    for p in placements:
        if p.object_type not in eligible_types:
            missing.append(p.object_type)
            eligible_types.add(p.object_type)  # 중복 방지

    if not missing:
        return eligible

    # 미등록 기물 → 기본 규격으로 생성 + DB INSERT
    import os
    DEFAULT_SPECS = {
        "character":  {"width_mm": 800, "depth_mm": 150, "height_mm": 2000, "category": "character", "material": "FRP"},
        "shelf":      {"width_mm": 1200, "depth_mm": 400, "height_mm": 1200, "category": "shelf", "material": "wood_painted"},
        "display":    {"width_mm": 1200, "depth_mm": 600, "height_mm": 800, "category": "display", "material": "wood_painted"},
        "photo":      {"width_mm": 2000, "depth_mm": 200, "height_mm": 2400, "category": "photo_zone", "material": "FRP"},
        "banner":     {"width_mm": 600, "depth_mm": 100, "height_mm": 2000, "category": "signage", "material": "fabric_metal_frame"},
        "pos":        {"width_mm": 800, "depth_mm": 600, "height_mm": 1000, "category": "counter", "material": "wood_painted"},
    }

    new_assets = []
    for obj_type in missing:
        # 카테고리 키워드 매칭으로 기본 규격 결정
        spec = DEFAULT_SPECS.get("character")  # fallback
        for keyword, s in DEFAULT_SPECS.items():
            if keyword in obj_type.lower():
                spec = s
                break

        asset = {
            "object_type": obj_type,
            "brand_id": brand_id,
            **spec,
            "can_join": False,
            "overlap_margin_mm": 0,
        }
        new_assets.append(asset)
        eligible.append(asset)
        print(f"[GAP] Provisioned: {obj_type} → {spec['width_mm']}x{spec['depth_mm']}x{spec['height_mm']}mm ({spec['category']})")

    # Supabase DB INSERT (영속화)
    try:
        url = os.getenv("SUPABASE_URL")
        key = os.getenv("SUPABASE_KEY")
        if url and key:
            from supabase import create_client
            client = create_client(url, key)
            for asset in new_assets:
                row = {
                    "object_type": asset["object_type"],
                    "brand_id": asset["brand_id"],
                    "width_mm": asset["width_mm"],
                    "depth_mm": asset["depth_mm"],
                    "height_mm": asset["height_mm"],
                    "category": asset["category"],
                    "material": asset["material"],
                }
                client.table("furniture_standards").insert(row).execute()
                print(f"[GAP] DB INSERT: {asset['object_type']} → furniture_standards")
    except Exception as e:
        print(f"[GAP] DB INSERT failed: {e} — in-memory only")

    print(f"[GAP] Total provisioned: {len(new_assets)} new assets")
    return eligible


def _build_floor_viz(space_data: dict, placed: list[dict] | None = None) -> dict:
    """3D 바닥 동선 시각화용 데이터 추출 + 부동선(Sub-path) 생성."""
    # slot별 walk_mm + zone_label + 좌표
    slots = []
    for key, val in space_data.items():
        if isinstance(val, dict) and "zone_label" in val and key != "floor":
            slots.append({
                "x_mm": val.get("x_mm", 0),
                "y_mm": val.get("y_mm", 0),
                "walk_mm": val.get("walk_mm", 0),
                "zone_label": val.get("zone_label", "unknown"),
            })

    # Main Artery(Spine) 좌표 리스트
    main_artery_coords = []
    artery = space_data.get("fire", {}).get("main_artery")
    if artery and hasattr(artery, "coords"):
        main_artery_coords = [
            [round(x, 1), round(y, 1)] for x, y in artery.coords
        ]

    # 부동선(Sub-path): 배치 후 미커버 구역 순회 복귀 루프
    sub_path_coords = []
    if placed and artery:
        sub_path_coords = _build_sub_path(space_data, placed, artery)

    # walk_mm 범위 (그라데이션용)
    walk_values = [s["walk_mm"] for s in slots] if slots else [0]
    max_walk = max(walk_values) if walk_values else 1

    # 입구 좌표 추출 — space_data에 저장된 전체 입구 좌표
    entrance_coords = []
    for ec in space_data.get("_entrance_coords_mm", []):
        entrance_coords.append([round(ec[0], 1), round(ec[1], 1)])

    return {
        "slots": slots,
        "main_artery": main_artery_coords,
        "sub_path": sub_path_coords,
        "entrances": entrance_coords,
        "max_walk_mm": max_walk,
    }


def _build_sub_path(
    space_data: dict,
    placed: list[dict],
    main_artery,
) -> list[list[float]]:
    """
    부동선(Sub-path) — 외곽 복귀 루프 (100% 생성 보장).

    주동선(Spine) 종점에서 출발하여 Spine 반대편 외곽을 의무 우회한 뒤
    입구로 복귀하는 경로. 배치된 기물이 모두 Spine 근처여도 반드시 생성.

    알고리즘:
    1. Spine이 지나지 않는 반대편 외곽에 최소 경유점(Mandatory Waypoints) 산출
    2. 배치된 기물 중 Spine에서 먼 것을 추가 경유점으로 병합
    3. Spine 종점 → 외곽 경유점 + 기물 경유점 → 입구, nearest-neighbor 순회
    4. 각 구간을 Dijkstra로 연결 (오브젝트 footprint 회피)
    """
    import networkx as nx
    from shapely.geometry import Point, Polygon as ShapelyPolygon

    floor_poly = space_data.get("floor", {}).get("polygon")
    if not floor_poly:
        return []

    spine_coords = list(main_artery.coords)
    spine_start = spine_coords[0]
    spine_end = spine_coords[-1]
    minx, miny, maxx, maxy = floor_poly.bounds
    cx_floor = (minx + maxx) / 2
    cy_floor = (miny + maxy) / 2

    # ── 1) 배치된 기물 중 Spine에서 먼 것을 경유점으로 수집 ────────────
    far_object_coords = []
    far_object_types = []
    for obj in placed:
        ox = obj.get("center_x_mm", 0)
        oy = obj.get("center_y_mm", 0)
        dist = main_artery.distance(Point(ox, oy))
        if dist > 2000:  # adjacent(2m) 밖
            far_object_coords.append((ox, oy))
            far_object_types.append(obj.get("object_type", ""))

    # ── 2) Fallback: 기물이 없으면 Spine 반대편 외곽 경유 ─────────────
    spine_avg_x = sum(c[0] for c in spine_coords) / len(spine_coords)
    spine_on_left = spine_avg_x < cx_floor
    margin = min(maxx - minx, maxy - miny) * 0.1

    if not far_object_coords:
        # 기물 전부 adjacent — 반대편 외곽 의무 경유
        if spine_on_left:
            far_x = maxx - margin
            fallback = [(far_x, maxy - margin), (far_x, cy_floor), (far_x, miny + margin)]
            side = "우측(fallback)"
        else:
            far_x = minx + margin
            fallback = [(far_x, maxy - margin), (far_x, cy_floor), (far_x, miny + margin)]
            side = "좌측(fallback)"
        merged = [(x, y) for x, y in fallback if floor_poly.contains(Point(x, y))]
        if not merged:
            merged = [fallback[1]]  # 최소 중앙 1점
    else:
        # 기물 기반 경유점 — 중복 제거 (2m 이내 병합)
        merged = []
        for wp in far_object_coords:
            too_close = any(Point(wp).distance(Point(e)) < 2000 for e in merged)
            if not too_close:
                merged.append(wp)
        side = f"기물 {len(merged)}개"

    # nearest-neighbor: Spine 종점에서 시작
    ordered = []
    remaining = list(merged)
    current = spine_end

    while remaining:
        nearest_wp = min(remaining, key=lambda v: Point(current).distance(Point(v)))
        ordered.append(nearest_wp)
        current = nearest_wp
        remaining.remove(nearest_wp)

    waypoints = [spine_end] + ordered + [spine_start]

    # ── 4) 오브젝트 footprint 장애물 → 그래프 재구축 → Dijkstra ──────
    dead_zones = list(space_data.get("dead_zones", []))
    for obj in placed:
        bx = obj.get("bbox_bounds", [])
        if len(bx) == 4:
            obj_poly = ShapelyPolygon([
                (bx[0], bx[1]), (bx[2], bx[1]),
                (bx[2], bx[3]), (bx[0], bx[3]),
            ])
            dead_zones.append(obj_poly.buffer(300))

    try:
        from app.agents.corridor_graph import build_corridor_graph, nearest_node
    except ImportError:
        return []

    G, nodes = build_corridor_graph(floor_poly, dead_zones=dead_zones)
    if not nodes:
        return []

    all_coords: list[tuple[float, float]] = []
    for i in range(len(waypoints) - 1):
        start_node = nearest_node(nodes, waypoints[i])
        end_node = nearest_node(nodes, waypoints[i + 1])

        if start_node == end_node:
            if not all_coords:
                all_coords.append(nodes[start_node])
            continue

        try:
            path = nx.shortest_path(G, start_node, end_node, weight="weight")
            segment = [nodes[n] for n in path]

            if all_coords and segment:
                if (abs(all_coords[-1][0] - segment[0][0]) < 1 and
                        abs(all_coords[-1][1] - segment[0][1]) < 1):
                    segment = segment[1:]
            all_coords.extend(segment)
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            if not all_coords:
                all_coords.append(waypoints[i])
            all_coords.append(waypoints[i + 1])

    # 시작/끝점을 실제 입구 좌표로 치환 (그리드 스냅 오차 제거)
    entrance_coords_mm = space_data.get("_entrance_coords_mm", [])
    if all_coords and entrance_coords_mm:
        # 끝점 = MAIN 입구 (항상 첫 번째)
        all_coords[-1] = entrance_coords_mm[0]
        # 시작점 = 2번째 입구(있으면) 또는 Spine 종점
        if len(entrance_coords_mm) >= 2:
            all_coords[0] = entrance_coords_mm[-1]
        else:
            all_coords[0] = spine_end

    result = [[round(x, 1), round(y, 1)] for x, y in all_coords]
    print(f"[Pipeline] sub_path: {side}, "
          f"far_objects={len(far_object_coords)}, "
          f"merged={len(merged)}, {len(result)} grid nodes")
    if far_object_types:
        print(f"[Pipeline] sub_path 경유 기물: {far_object_types}")
    return result


def _build_summary(space_data, placed, dropped, fallback_used, verification):
    floor = space_data.get("floor", {})
    zone_dist: dict[str, int] = {}
    for p in placed:
        z = p.get("zone_label", "unknown")
        zone_dist[z] = zone_dist.get(z, 0) + 1

    slot_count = sum(
        1 for k, v in space_data.items()
        if isinstance(v, dict) and "zone_label" in v and k != "floor"
    )
    total = len(placed) + len(dropped)

    return SummaryReport(
        total_area_sqm=floor.get("usable_area_sqm", 0),
        zone_distribution=zone_dist,
        placed_count=len(placed),
        dropped_count=len(dropped),
        success_rate=round(len(placed) / total, 3) if total > 0 else 0.0,
        fallback_used=fallback_used,
        slot_count=slot_count,
        verification_passed=verification.passed,
    )
