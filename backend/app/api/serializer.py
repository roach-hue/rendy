"""직렬화 유틸리티 — Shapely/numpy 타입 재귀 제거."""


def strip_shapely(obj):
    """Shapely 객체 + numpy 타입 재귀 제거/변환 (JSON 직렬화 보장)."""
    import numpy as np
    from shapely.geometry.base import BaseGeometry
    if isinstance(obj, BaseGeometry):
        return None
    if isinstance(obj, dict):
        return {k: strip_shapely(v) for k, v in obj.items() if not isinstance(v, BaseGeometry)}
    if isinstance(obj, (list, tuple)):
        return [strip_shapely(v) for v in obj if not isinstance(v, BaseGeometry)]
    if isinstance(obj, (str, bool, type(None))):
        return obj
    if isinstance(obj, (int, np.integer)):
        return int(obj)
    if isinstance(obj, (float, np.floating)):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    return str(obj)
