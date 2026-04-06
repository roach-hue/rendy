"""Dead Zone 생성 — 설비 buffer + inaccessible rooms + inner walls."""
import math

from shapely.geometry import LineString, Point, Polygon
from shapely.ops import unary_union

DEAD_ZONE_BUFFER = {
    "sprinkler": 300,
    "fire_hydrant": 500,
    "electrical_panel": 600,
}

INNER_WALL_BUFFER_MM = 150


def generate_dead_zones(
    sprinklers_mm: list[tuple[float, float]],
    hydrants_mm: list[tuple[float, float]],
    panels_mm: list[tuple[float, float]],
    inaccessible_polys: list[Polygon],
    inner_walls_raw: list,
    usable_poly: Polygon,
    scale: float,
    ox: float,
    oy: float,
    floor_px_min_x: float,
    floor_px_min_y: float,
) -> tuple[list, list[LineString]]:
    """
    Returns: (dead_zones, inner_wall_linestrings)
    """
    dead_zones = []

    # 설비 buffer
    for pt in sprinklers_mm:
        dead_zones.append(Point(pt).buffer(DEAD_ZONE_BUFFER["sprinkler"]))
    for pt in hydrants_mm:
        dead_zones.append(Point(pt).buffer(DEAD_ZONE_BUFFER["fire_hydrant"]))
    for pt in panels_mm:
        dead_zones.append(Point(pt).buffer(DEAD_ZONE_BUFFER["electrical_panel"]))

    # inaccessible rooms
    for room_poly in inaccessible_polys:
        if room_poly.is_valid and room_poly.area > 0:
            dead_zones.append(room_poly)
    if inaccessible_polys:
        print(f"[Agent2] inaccessible rooms: {len(inaccessible_polys)} → dead zones")

    # inner walls → LineString 정비 + dead zone
    s = scale
    inner_wall_linestrings: list[LineString] = []
    for wall in inner_walls_raw:
        wx0, wy0 = wall.start_px
        wx1, wy1 = wall.end_px
        if wx0 < floor_px_min_x * 0.8 or wy0 < floor_px_min_y * 0.8:
            wx0 += floor_px_min_x
            wy0 += floor_px_min_y
            wx1 += floor_px_min_x
            wy1 += floor_px_min_y
        wall_ls = LineString([
            (wx0 * s - ox, wy0 * s - oy),
            (wx1 * s - ox, wy1 * s - oy),
        ])
        if wall_ls.length > 0:
            clipped = usable_poly.intersection(wall_ls)
            if not clipped.is_empty and clipped.length > 0:
                if clipped.geom_type == "MultiLineString":
                    clipped = max(clipped.geoms, key=lambda g: g.length)
                if clipped.geom_type == "LineString" and clipped.length > 10:
                    inner_wall_linestrings.append(clipped)
                    dead_zones.append(clipped.buffer(INNER_WALL_BUFFER_MM))

    if inner_wall_linestrings:
        print(f"[Agent2] inner walls: {len(inner_wall_linestrings)} LineStrings saved, "
              f"dead zones +{len(inner_wall_linestrings)} (buffer={INNER_WALL_BUFFER_MM}mm)")

    return dead_zones, inner_wall_linestrings
