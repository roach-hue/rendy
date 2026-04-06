"""오브젝트 CRUD — Supabase furniture_standards 테이블."""
import os
from supabase import create_client


def _get_client():
    return create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))


def list_objects(brand_id: str = "sanrio") -> list:
    r = _get_client().table("furniture_standards").select("*").eq("brand_id", brand_id).execute()
    return r.data


def create_object(body: dict) -> dict:
    r = _get_client().table("furniture_standards").insert(body).execute()
    print(f"[Objects] created: {body.get('object_type')}")
    return r.data[0] if r.data else {}


def update_object(object_type: str, body: dict) -> dict:
    r = _get_client().table("furniture_standards").update(body).eq("object_type", object_type).execute()
    print(f"[Objects] updated: {object_type}")
    return r.data[0] if r.data else {}


def delete_object(object_type: str, brand_id: str = "sanrio") -> dict:
    _get_client().table("furniture_standards").delete().eq("object_type", object_type).eq("brand_id", brand_id).execute()
    print(f"[Objects] deleted: {object_type} (brand: {brand_id})")
    return {"deleted": object_type}
