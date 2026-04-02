---
name: 공간 연산 스킬
description: Agent 2 후반부가 도면 데이터를 mm 변환하고 Dead Zone, 기준점, zone, NetworkX를 계산하는 프레임워크
---

# 공간 연산 스킬 (Spatial Computation Skill)

## 목적
사용자 수정이 반영된 `auto_detected` 데이터를 받아 최종 `space_data`를 확정. 코드 순회 루프와 Agent 3이 사용할 모든 공간 수치를 저장.

> ⚠️ 이 모듈은 순수 코드 — LLM 개입 없음

---

## 처리 순서

### Step 1: 픽셀 → mm 변환

```python
# auto_detected의 모든 좌표를 mm로 변환
x_mm = x_px * scale_mm_per_px
y_mm = y_px * scale_mm_per_px

# floor_polygon_px → Shapely Polygon (mm)
space_data["floor"]["polygon"] = Polygon([(x*scale, y*scale) for x,y in floor_polygon_px])
space_data["floor"]["usable_area_sqm"] = polygon.area / 1_000_000  # mm² → m²

# max_object_w_mm: bounding box 단축 기준 (너무 큰 오브젝트 필터링용)
bounds = space_data["floor"]["polygon"].bounds  # (minx, miny, maxx, maxy)
space_data["floor"]["max_object_w_mm"] = min(
    bounds[2] - bounds[0],  # x 방향 폭
    bounds[3] - bounds[1]   # y 방향 폭
)
```

### Step 1-b: floor_polygon 차감 (배치 불가 영역)

```python
# 사용자 마킹 UI에서 확정된 inaccessible_rooms를 floor_polygon에서 차감
from shapely.ops import unary_union

room_polygons = [Polygon([(x*scale, y*scale) for x,y in room["polygon_px"]])
                 for room in auto_detected["inaccessible_rooms"]]

if room_polygons:
    space_data["floor"]["polygon"] = space_data["floor"]["polygon"].difference(
        unary_union(room_polygons)
    )
```

> 이 시점부터 floor_polygon은 실제 배치 가능 영역만 포함. NetworkX 격자점이 폐쇄 방 내부에 생성되지 않음.

### Step 1-c: 내부 벽 → wall_linestring 추가

```python
# 사용자 마킹 UI에서 확정된 inner_walls를 space_data에 추가
for i, wall in enumerate(auto_detected["inner_walls"]):
    key = f"inner_wall_{i}"
    x1, y1 = wall["start_px"][0] * scale, wall["start_px"][1] * scale
    x2, y2 = wall["end_px"][0] * scale, wall["end_px"][1] * scale
    space_data[key] = {
        "wall_linestring": LineString([(x1, y1), (x2, y2)]),
        "wall_normal": None,   # 내부 벽: 양면 배치 가능 — placement_slot 생성 시 판단
        "zone_label": None,    # Agent 2 후반부 Step 4에서 walk_mm 기반 부여
    }
```

### Step 2: Dead Zone 생성

```
설비(스프링클러, 소화전, 분전반) 위치 기반으로 접근 금지 구역 생성.

Dead Zone 반경:
- 스프링클러: 반경 없음 (천장 설비) — 바닥 Dead Zone 미생성
- 소화전: 반경 1000mm
- 분전반: 반경 1000mm

Dead Zone = Shapely buffer(반경)으로 생성
→ 배치 시 오브젝트 bbox가 Dead Zone과 교차하면 배치 불가
```

### Step 3: placement_slot 생성

```python
# 각 벽면의 중심점에 placement_slot 생성
space_data["north_wall_mid"] = {
    "x_mm": 2300,
    "y_mm": 3800,
    "wall_linestring": LineString([(0, 4000), (6000, 4000)]),
    "wall_normal": "south",       # 벽 앞면이 향하는 방향
    "zone_label": "mid_zone",
    "shelf_capacity": 3           # 해당 위치에 수용 가능한 선반 수
}
```

> 벽을 LineString 객체로 저장 — 단일 좌표(wall_surface_y) 방식 폐기 (architecture_decisions.md Issue 8)
> wall_normal은 벽 표면에서 바깥→안쪽 방향

### Step 4: NetworkX 격자 그래프 + 보행 거리

```
1. 바닥 polygon 내부에 격자점 생성
2. Dead Zone 내부 격자점 제거
3. 인접 격자점 간 edge 연결
4. 입구에서 각 격자점까지의 최단 경로 계산
5. 그래프 객체는 dict에 저장 금지 — 함수 내 변수로만 유지
```

### Step 5: walk_mm 계산 및 zone 임계값 설정

```python
# G가 Step 4에서 생성된 후 실행
for point_key, point_node in grid_point_nodes.items():
    walk_mm = nx.shortest_path_length(G, entrance_node, point_node, weight="weight")
    space_data[point_key]["walk_mm"] = walk_mm

# zone 임계값 설정 (수치는 도면 테스트 후 결정 — Issue 16)
space_data["zones"] = {
    "entrance_zone": {"walk_mm_min": 0,   "walk_mm_max": 400},
    "mid_zone":      {"walk_mm_min": 400, "walk_mm_max": 700},
    "deep_zone":     {"walk_mm_min": 700, "walk_mm_max": float("inf")},
}

# placement_slot zone_label 자동 부여
for slot_key in placement_slots:
    wm = space_data[slot_key]["walk_mm"]
    space_data[slot_key]["zone_label"] = assign_zone_by_walk_mm(wm, space_data["zones"])
```

> zone polygon 경계(Polygon 객체) 방식 폐기 — convex decomposition 불필요 (Issue 16)

### Step 5-b: Main Artery 캐싱 (Issue 19)

```python
# 복수 입구: super-source 노드 기준 (Issue 17 복수 입구 처리와 동일)
# 비상구 별도 존재 시 → entrance to emergency_exit
# 단일 입구 시 → entrance to farthest reachable node
if emergency_exit_node:
    target = emergency_exit_node
else:
    # 가장 먼 노드 = 최장 대피 경로
    target = max(grid_point_nodes.values(),
                 key=lambda n: nx.shortest_path_length(G, entrance_node, n, weight="weight"))

artery_nodes = nx.shortest_path(G, entrance_node, target, weight="weight")
space_data["fire"]["main_artery"] = LineString([node_coords[n] for n in artery_nodes])
```

> main_artery는 도면 구조 기반 — 오브젝트 배치와 무관. Global Reset 후에도 파기하지 않음.

### Step 6: Agent 3용 자연어 요약 생성

```python
# Agent 3에는 수치가 아닌 자연어 요약만 전달
summaries = {
    "north_wall_mid": "north_wall_mid: mid_zone, shelf 3개 수용 가능",
    "south_wall_left": "south_wall_left: entrance_zone, 입구 인접"
}
```

> 이중 소비 구조: 동일 데이터를 코드용(수치)과 LLM용(자연어) 두 형태로 동시 저장

---

## space_data 확정 저장 구조

```python
space_data = {
    # 공간 수치
    "floor": {
        "polygon": Polygon(...),
        "usable_area_sqm": 36.0,
        "max_object_w_mm": 2000
    },

    # 기준점 (코드용 + Agent 3용)
    "north_wall_mid": {
        "x_mm": 2300,
        "y_mm": 3800,
        "wall_linestring": LineString([(0,4000),(6000,4000)]),
        "wall_normal": "south",
        "zone_label": "mid_zone",
        "shelf_capacity": 3
    },

    # zone 임계값 (Issue 16 — walk_mm 기반)
    "zones": {
        "entrance_zone": {"walk_mm_min": 0,   "walk_mm_max": 400},
        "mid_zone":      {"walk_mm_min": 400, "walk_mm_max": 700},
        "deep_zone":     {"walk_mm_min": 700, "walk_mm_max": float("inf")},
    },

    # 소방/시공 기준 (하드코딩)
    "fire": {
        "main_corridor_min_mm": 900,
        "emergency_path_min_mm": 1200,
        "main_artery": LineString(...)   # Step 5-b에서 캐싱 (Issue 19)
    },
    "construction": {
        "wall_clearance_mm": 300
    },

    # 면책
    "infra": {
        "disclaimer": ["electrical_panel"]
    }
}
```

---

## 주의사항

- 이 모듈 실행 후 space_data가 확정 — 이후 파이프라인에서 space_data 구조 변경 금지
- NetworkX 그래프 객체를 space_data dict에 넣지 않음 — 필요 시 재생성
- zone 경계가 floor polygon을 완전히 커버하는지 검증
- placement_slot가 Dead Zone 내부에 위치하지 않는지 검증
