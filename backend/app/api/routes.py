from fastapi import APIRouter, File, UploadFile, HTTPException
from pydantic import BaseModel
from app.parsers.factory import get_parser
from app.schemas.drawings import ParsedDrawings

router = APIRouter()


class UserDims(BaseModel):
    width_mm: float
    height_mm: float


class SpaceDataRequest(BaseModel):
    drawings: ParsedDrawings
    scale_mm_per_px: float
    entrance_px: tuple[float, float] | None = None
    user_dims: UserDims | None = None


@router.post("/space-data")
def build_space_data(body: SpaceDataRequest) -> dict:
    """
    사용자 마킹 확정 후 Agent 2 후반부 실행.
    ParsedDrawings + scale → space_data 반환.
    user_dims가 있으면 사용자 입력 치수로 polygon 재구성.
    """
    from app.agents.agent2_back import run

    drawings = body.drawings

    # 사용자 치수 입력 시 polygon 재구성
    if body.user_dims:
        drawings = _rebuild_polygon(drawings, body.user_dims, body.scale_mm_per_px)

    sd = run(
        drawings=drawings,
        scale_mm_per_px=body.scale_mm_per_px,
        user_entrance_px=body.entrance_px,
    )
    return _serialize_space_data(sd)


def _rebuild_polygon(
    drawings: ParsedDrawings,
    user_dims: UserDims,
    scale: float,
) -> ParsedDrawings:
    """사용자 입력 가로·세로(mm)로 건물 외벽 polygon 재구성."""
    fp = drawings.floor_plan
    xs = [p[0] for p in fp.floor_polygon_px]
    ys = [p[1] for p in fp.floor_polygon_px]

    # 기존 polygon 중심점 기준으로 사용자 치수 사각형 생성
    cx = (min(xs) + max(xs)) / 2
    cy = (min(ys) + max(ys)) / 2
    half_w = (user_dims.width_mm / scale) / 2
    half_h = (user_dims.height_mm / scale) / 2

    new_polygon: list[tuple[float, float]] = [
        (cx - half_w, cy - half_h),
        (cx + half_w, cy - half_h),
        (cx + half_w, cy + half_h),
        (cx - half_w, cy + half_h),
    ]

    print(f"[routes] polygon rebuilt: center=({cx:.0f},{cy:.0f}), "
          f"size={user_dims.width_mm}x{user_dims.height_mm}mm → "
          f"{half_w*2:.0f}x{half_h*2:.0f}px")

    # 새 ParsedDrawings 생성 (나머지 필드 유지)
    new_fp = fp.model_copy(update={"floor_polygon_px": new_polygon})
    return drawings.model_copy(update={"floor_plan": new_fp})


def _serialize_space_data(sd: dict) -> dict:
    """Shapely 객체 등 직렬화 불가 값 제거 (재귀)."""
    return _strip_shapely(sd)


class ScaleCorrection(BaseModel):
    actual_length_mm: float   # 사용자가 입력한 실제 치수 (mm)
    ref_start_px: tuple[float, float]  # 해당 치수의 픽셀 시작점
    ref_end_px: tuple[float, float]    # 해당 치수의 픽셀 끝점


@router.post("/scale-correct")
def correct_scale(body: ScaleCorrection) -> dict:
    """
    사용자가 도면의 실제 치수를 직접 입력하면 scale_mm_per_px 재계산.
    마킹 UI에서 scale_confirmed=False일 때 호출.
    """
    sx, sy = body.ref_start_px
    ex, ey = body.ref_end_px
    px_len = ((ex - sx) ** 2 + (ey - sy) ** 2) ** 0.5
    if px_len == 0:
        raise HTTPException(status_code=422, detail="시작점과 끝점이 동일합니다.")
    scale = body.actual_length_mm / px_len
    return {"scale_mm_per_px": scale, "scale_confirmed": True}



class PlacementRequest(BaseModel):
    space_data_serialized: dict  # _serialize_space_data 후의 dict
    brand_data: dict
    scale_mm_per_px: float
    drawings_json: dict  # ParsedDrawings.model_dump()


@router.post("/placement")
def run_placement(body: PlacementRequest) -> dict:
    """
    전체 배치 파이프라인: Agent 3 기획 → 배치 엔진 → 검증 → 리포트 + .glb
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

    try:
        print("[Pipeline] placement request received")
        drawings = ParsedDrawings.model_validate(body.drawings_json)
        sd = run_agent2(drawings=drawings, scale_mm_per_px=body.scale_mm_per_px)

        eligible = select_eligible_objects(sd, body.brand_data)
        print(f"[Pipeline] eligible objects: {len(eligible)}")

        placements = plan_placement(eligible, sd, body.brand_data)
        print(f"[Pipeline] Agent 3 placements: {len(placements)}")

        result = run_with_fallback(placements, eligible, sd, body.brand_data)
        print(f"[Pipeline] placed: {len(result['placed'])}, dropped: {len(result['dropped'])}")

        verification = verify_placement(result["placed"], sd)

        report = generate_report(
            result["placed"], result["dropped"], verification.model_dump(),
            sd, body.brand_data, result["fallback_used"],
        )

        glb_bytes = export_glb(result["placed"], sd)
        glb_b64 = base64.b64encode(glb_bytes).decode()

        summary = _build_summary(
            sd, result["placed"], result["dropped"],
            result["fallback_used"], verification,
        )

        response = _strip_shapely({
            "placed": result["placed"],
            "dropped": result["dropped"],
            "verification": verification.model_dump(),
            "report": report,
            "glb_base64": glb_b64,
            "log": result["log"],
            "summary": summary.model_dump(),
        })
        return response
    except Exception as e:
        from app.core.exceptions import (
            RendyBaseError, LLMTimeoutError, LLMParsingError, LLMValidationError,
            ParserError, PlacementError, ExternalServiceError,
        )
        print(f"[Pipeline] ERROR: {type(e).__name__}: {e}")
        traceback.print_exc()

        if isinstance(e, (LLMTimeoutError, LLMParsingError)):
            raise HTTPException(status_code=502, detail=f"LLM 오류: {e}")
        if isinstance(e, LLMValidationError):
            raise HTTPException(status_code=422, detail=f"LLM 출력 검증 실패: {e}")
        if isinstance(e, ParserError):
            raise HTTPException(status_code=422, detail=f"도면 파싱 오류: {e}")
        if isinstance(e, PlacementError):
            raise HTTPException(status_code=500, detail=f"배치 엔진 오류: {e}")
        if isinstance(e, ExternalServiceError):
            raise HTTPException(status_code=503, detail=f"외부 서비스 오류: {e}")
        if isinstance(e, RendyBaseError):
            raise HTTPException(status_code=500, detail=f"시스템 오류: {e}")
        raise HTTPException(status_code=500, detail=str(e))


def _strip_shapely(obj):
    """Shapely 객체 + numpy 타입 재귀 제거/변환 (JSON 직렬화 보장)."""
    import numpy as np
    from shapely.geometry.base import BaseGeometry
    if isinstance(obj, BaseGeometry):
        return None
    if isinstance(obj, dict):
        return {k: _strip_shapely(v) for k, v in obj.items() if not isinstance(v, BaseGeometry)}
    if isinstance(obj, (list, tuple)):
        return [_strip_shapely(v) for v in obj if not isinstance(v, BaseGeometry)]
    if isinstance(obj, (str, bool, type(None))):
        return obj
    if isinstance(obj, (int, np.integer)):
        return int(obj)
    if isinstance(obj, (float, np.floating)):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    return str(obj)


# ── 캐싱: space_data + brand_data 저장/로드 ─────────────────────────────────

import json as _json
from pathlib import Path as _Path

_CACHE_DIR = _Path(__file__).parent.parent.parent / "cache"


@router.post("/cache-save")
def cache_save(body: dict) -> dict:
    """3단계 확정 후 space_data + brand_data + drawings 캐싱."""
    _CACHE_DIR.mkdir(exist_ok=True)
    cache_file = _CACHE_DIR / "last_session.json"
    # Shapely 객체 제거 후 저장
    serializable = {k: v for k, v in body.items() if k != "space_data"}
    if "space_data" in body:
        serializable["space_data"] = _serialize_space_data_deep(body["space_data"])
    cache_file.write_text(_json.dumps(serializable, ensure_ascii=False, indent=2))
    print(f"[Cache] saved to {cache_file}")
    return {"saved": True}


@router.get("/cache-load")
def cache_load() -> dict:
    """캐싱된 세션 데이터 로드 — 1~3단계 건너뛰기."""
    cache_file = _CACHE_DIR / "last_session.json"
    if not cache_file.exists():
        raise HTTPException(status_code=404, detail="캐시 없음")
    data = _json.loads(cache_file.read_text())
    print(f"[Cache] loaded from {cache_file}")
    return data


def _serialize_space_data_deep(sd: dict) -> dict:
    """space_data에서 모든 Shapely 객체 재귀 제거."""
    return _strip_shapely(sd)


# ── 오브젝트 CRUD ───────────────────────────────────────────────────────────

@router.get("/objects")
def list_objects(brand_id: str = "sanrio") -> list:
    """furniture_standards 조회."""
    import os
    from supabase import create_client
    client = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))
    r = client.table("furniture_standards").select("*").eq("brand_id", brand_id).execute()
    return r.data


@router.post("/objects")
def create_object(body: dict) -> dict:
    """furniture_standards에 오브젝트 추가."""
    import os
    from supabase import create_client
    client = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))
    r = client.table("furniture_standards").insert(body).execute()
    print(f"[Objects] created: {body.get('object_type')}")
    return r.data[0] if r.data else {}


@router.put("/objects/{object_type}")
def update_object(object_type: str, body: dict) -> dict:
    """furniture_standards 오브젝트 수정."""
    import os
    from supabase import create_client
    client = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))
    r = client.table("furniture_standards").update(body).eq("object_type", object_type).execute()
    print(f"[Objects] updated: {object_type}")
    return r.data[0] if r.data else {}


@router.delete("/objects/{object_type}")
def delete_object(object_type: str, brand_id: str = "sanrio") -> dict:
    """furniture_standards 오브젝트 삭제."""
    import os
    from supabase import create_client
    client = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))
    client.table("furniture_standards").delete().eq("object_type", object_type).eq("brand_id", brand_id).execute()
    print(f"[Objects] deleted: {object_type} (brand: {brand_id})")
    return {"deleted": object_type}


@router.post("/brand")
async def extract_brand(
    brand_manual: UploadFile = File(..., description="브랜드 메뉴얼 PDF"),
) -> dict:
    """Agent 1 — 브랜드 메뉴얼 PDF에서 수치/규정 추출."""
    from app.agents.agent1_brand import extract
    pdf_bytes = await brand_manual.read()
    try:
        return extract(pdf_bytes)
    except Exception as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.post("/detect")
async def detect_floor_plan(
    floor_plan: UploadFile = File(..., description="평면도 파일 (DXF / PDF / 이미지)"),
    section_drawing: UploadFile | None = File(None, description="단면도 파일 (선택)"),
) -> dict:
    """
    도면 파일을 받아 바닥 polygon, 설비 위치, 천장 높이를 자동 감지.
    PDF일 때 preview_image_base64 포함.
    결과는 사용자 마킹 UI에서 확인/수정 후 /space-data로 확정.
    """
    floor_bytes = await floor_plan.read()
    section_bytes = await section_drawing.read() if section_drawing else None
    filename = floor_plan.filename or ""

    parser = get_parser(
        filename=filename,
        floor_bytes=floor_bytes,
        section_bytes=section_bytes,
    )

    try:
        result = await parser.parse()
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"도면 파싱 실패: {e}")

    response = result.model_dump()

    # PDF/DXF일 때 미리보기 이미지 생성 (img 태그로 표시 불가한 형식)
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext in ("pdf", "dxf"):
        preview_b64 = _generate_preview(floor_bytes, ext)
        if preview_b64:
            response["preview_image_base64"] = preview_b64

    return response


def _generate_preview(file_bytes: bytes, ext: str) -> str | None:
    """PDF/DXF → 첫 페이지 PNG 래스터화 → base64."""
    import base64
    try:
        if ext == "pdf":
            import fitz
            doc = fitz.open(stream=file_bytes, filetype="pdf")
            page = doc[0]
            pix = page.get_pixmap(matrix=fitz.Matrix(150 / 72, 150 / 72), alpha=False)
            png_bytes = pix.tobytes("png")
            print(f"[Preview] PDF → PNG: {len(png_bytes)} bytes")
            return base64.b64encode(png_bytes).decode()
        # DXF 미리보기는 ezdxf로 렌더링 가능하나 복잡 → 추후
    except Exception as e:
        print(f"[Preview] failed: {e}")
    return None


def _build_summary(
    space_data: dict,
    placed: list[dict],
    dropped: list[dict],
    fallback_used: bool,
    verification,
) -> "SummaryReport":
    """배치 결과 요약 생성."""
    from app.schemas.verification import SummaryReport

    floor = space_data.get("floor", {})
    total_area = floor.get("usable_area_sqm", 0)

    # zone 분포
    zone_dist: dict[str, int] = {}
    for p in placed:
        z = p.get("zone_label", "unknown")
        zone_dist[z] = zone_dist.get(z, 0) + 1

    # slot 수
    slot_count = sum(
        1 for k, v in space_data.items()
        if isinstance(v, dict) and "zone_label" in v and k != "floor"
    )

    placed_count = len(placed)
    dropped_count = len(dropped)
    total = placed_count + dropped_count
    success_rate = placed_count / total if total > 0 else 0.0

    return SummaryReport(
        total_area_sqm=total_area,
        zone_distribution=zone_dist,
        placed_count=placed_count,
        dropped_count=dropped_count,
        success_rate=round(success_rate, 3),
        fallback_used=fallback_used,
        slot_count=slot_count,
        verification_passed=verification.passed,
    )
