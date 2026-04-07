"""Supabase 클라이언트 싱글톤. 전체 백엔드에서 공유."""
import os

_client = None


def get_client():
    """Supabase 클라이언트 반환. 미설정 시 None."""
    global _client
    if _client is not None:
        return _client

    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")
    if not url or not key:
        return None

    from supabase import create_client
    _client = create_client(url, key)
    return _client
