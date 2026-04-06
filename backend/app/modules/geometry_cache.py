"""
순수 기하학 해시 캐싱 — SHA-256 + DB Upsert.

해시 키: primitive_type + normalized(width, height, depth)
정규화: 소수점 첫째 자리 반올림 (부동소수점 오차 방지)
위치/회전/ID 등 가변 데이터 절대 배제.

DB: Supabase geometry_cache 테이블 (Get or Create).
Fallback: DB 미연결 시 인메모리 캐시.
"""
import hashlib
import os
from typing import Optional

# 등신대/배너 등 Plane형 기물의 최소 두께 (mm)
# glb_exporter.py에서도 이 상수를 import하여 사용.
MIN_DEPTH_MM = 20


def normalize(value: float) -> float:
    """소수점 첫째 자리 반올림. 부동소수점 오차 방지."""
    return round(value, 1)


def compute_geometry_hash(
    primitive_type: str,
    width_mm: float,
    depth_mm: float,
    height_mm: float,
) -> str:
    """
    순수 기하학 SHA-256 해시 (64자).
    position, rotation, id 등 가변 데이터 배제.
    """
    nw = normalize(width_mm)
    nd = normalize(depth_mm)
    nh = normalize(height_mm)
    key = f"{primitive_type}:{nw}:{nd}:{nh}"
    return hashlib.sha256(key.encode()).hexdigest()


def get_primitive_type(category: str) -> str:
    """category 기반 primitive 타입 판정."""
    if any(kw in category.lower() for kw in ("cylinder", "round", "column", "pillar")):
        return "CYLINDER"
    return "BOX"


# ── 인메모리 캐시 (DB fallback) ──────────────────────────────────────────────
_mem_cache: dict[str, dict] = {}


def get_or_create(
    obj_type: str,
    category: str,
    width_mm: float,
    depth_mm: float,
    height_mm: float,
) -> dict:
    """
    geometry 해시 조회 → Cache Hit이면 기존 ID, Miss면 신규 등록.
    DB(Supabase) 우선, 실패 시 인메모리 fallback.

    Returns:
        {"geometry_id": str, "primitive_type": str, "cache_hit": bool,
         "width_mm": float, "depth_mm": float, "height_mm": float}
    """
    if depth_mm < MIN_DEPTH_MM:
        depth_mm = MIN_DEPTH_MM

    ptype = get_primitive_type(category)
    nw = normalize(width_mm)
    nd = normalize(depth_mm)
    nh = normalize(height_mm)
    geo_hash = compute_geometry_hash(ptype, nw, nd, nh)

    params = {"width_mm": nw, "depth_mm": nd, "height_mm": nh}

    # DB 시도
    db_result = _db_get_or_create(geo_hash, ptype, params)
    if db_result is not None:
        return db_result

    # 인메모리 fallback
    if geo_hash in _mem_cache:
        return {**_mem_cache[geo_hash], "cache_hit": True}

    entry = {
        "geometry_id": geo_hash,
        "primitive_type": ptype,
        "width_mm": nw,
        "depth_mm": nd,
        "height_mm": nh,
    }
    _mem_cache[geo_hash] = entry
    return {**entry, "cache_hit": False}


def _db_get_or_create(
    hash_key: str,
    primitive_type: str,
    parameters: dict,
) -> Optional[dict]:
    """Supabase geometry_cache Upsert. 실패 시 None (인메모리 fallback)."""
    try:
        url = os.getenv("SUPABASE_URL")
        key = os.getenv("SUPABASE_KEY")
        if not url or not key:
            return None

        from supabase import create_client
        client = create_client(url, key)

        # GET: 기존 해시 조회
        existing = client.table("geometry_cache").select("*").eq("hash_key", hash_key).execute()
        if existing.data:
            row = existing.data[0]
            return {
                "geometry_id": row["hash_key"],
                "primitive_type": row["primitive_type"],
                "width_mm": parameters["width_mm"],
                "depth_mm": parameters["depth_mm"],
                "height_mm": parameters["height_mm"],
                "cache_hit": True,
            }

        # CREATE: 신규 등록
        import json
        client.table("geometry_cache").insert({
            "hash_key": hash_key,
            "primitive_type": primitive_type,
            "parameters": json.dumps(parameters),
        }).execute()

        return {
            "geometry_id": hash_key,
            "primitive_type": primitive_type,
            "width_mm": parameters["width_mm"],
            "depth_mm": parameters["depth_mm"],
            "height_mm": parameters["height_mm"],
            "cache_hit": False,
        }
    except Exception as e:
        print(f"[GeometryCache] DB error: {e} — using memory fallback")
        return None


def get_cache_stats() -> dict:
    """인메모리 캐시 통계."""
    return {"total_entries": len(_mem_cache), "entries": list(_mem_cache.keys())}


def clear_cache():
    """인메모리 캐시 초기화."""
    _mem_cache.clear()
