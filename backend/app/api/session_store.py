"""세션 영속화 — Supabase session_cache 테이블.

Key-Value 캐시 스토어. 배치 결과를 단일 JSONB로 저장.

테이블 스키마:
  CREATE TABLE session_cache (
    session_key TEXT PRIMARY KEY,
    placement_result JSONB NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
  );
"""
import json
import os

_TABLE = "session_cache"


def _get_client():
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")
    if not url or not key:
        return None
    from supabase import create_client
    return create_client(url, key)


def save_session(session_key: str, placement_result: dict) -> bool:
    """배치 결과를 DB에 저장. 성공 시 True."""
    client = _get_client()
    if not client:
        print("[SessionStore] Supabase 미설정 — DB 저장 skip")
        return False

    try:
        client.table(_TABLE).upsert({
            "session_key": session_key,
            "placement_result": json.loads(json.dumps(placement_result, default=str)),
        }, on_conflict="session_key").execute()
        print(f"[SessionStore] DB 저장: {session_key}")
        return True
    except Exception as e:
        print(f"[SessionStore] DB 저장 실패: {e}")
        return False


def load_session(session_key: str) -> dict | None:
    """DB에서 배치 결과 복원. 없으면 None."""
    client = _get_client()
    if not client:
        return None

    try:
        r = client.table(_TABLE).select("placement_result").eq(
            "session_key", session_key
        ).execute()
        if r.data and r.data[0].get("placement_result"):
            print(f"[SessionStore] DB 복원: {session_key}")
            return r.data[0]["placement_result"]
        return None
    except Exception as e:
        print(f"[SessionStore] DB 로드 실패: {e}")
        return None


def delete_session(session_key: str) -> bool:
    """세션 삭제."""
    client = _get_client()
    if not client:
        return False

    try:
        client.table(_TABLE).delete().eq("session_key", session_key).execute()
        print(f"[SessionStore] DB 삭제: {session_key}")
        return True
    except Exception as e:
        print(f"[SessionStore] DB 삭제 실패: {e}")
        return False
