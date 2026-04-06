"""캐시 서비스 — space_data + brand_data 저장/로드."""
import json
from pathlib import Path

from app.api.serializer import strip_shapely

_CACHE_DIR = Path(__file__).parent.parent.parent / "cache"


def save_cache(body: dict) -> dict:
    """3단계 확정 후 space_data + brand_data + drawings 캐싱."""
    _CACHE_DIR.mkdir(exist_ok=True)
    cache_file = _CACHE_DIR / "last_session.json"
    serializable = {k: v for k, v in body.items() if k != "space_data"}
    if "space_data" in body:
        serializable["space_data"] = strip_shapely(body["space_data"])
    cache_file.write_text(json.dumps(serializable, ensure_ascii=False, indent=2))
    print(f"[Cache] saved to {cache_file}")
    return {"saved": True}


def load_cache() -> dict | None:
    """캐싱된 세션 데이터 로드. 없으면 None."""
    cache_file = _CACHE_DIR / "last_session.json"
    if not cache_file.exists():
        return None
    data = json.loads(cache_file.read_text())
    print(f"[Cache] loaded from {cache_file}")
    return data
