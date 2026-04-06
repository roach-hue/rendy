"""
API 라우터 — 순수 Controller 계층.
비즈니스 로직 없음. 서비스 모듈 호출 + HTTP 응답 반환만 수행.
"""
import traceback

from fastapi import APIRouter, File, UploadFile, HTTPException
from pydantic import BaseModel

from app.schemas.drawings import ParsedDrawings
from app.parsers.factory import get_parser

router = APIRouter()


# ── Request 스키마 ────────────────────────────────────────────────────────────

class UserDims(BaseModel):
    width_mm: float
    height_mm: float


class SpaceDataRequest(BaseModel):
    drawings: ParsedDrawings
    scale_mm_per_px: float
    entrance_px: tuple[float, float] | None = None
    user_dims: UserDims | None = None


class ScaleCorrection(BaseModel):
    actual_length_mm: float
    ref_start_px: tuple[float, float]
    ref_end_px: tuple[float, float]


class PlacementRequest(BaseModel):
    space_data_serialized: dict
    brand_data: dict
    scale_mm_per_px: float
    drawings_json: dict


# ── 엔드포인트 ────────────────────────────────────────────────────────────────

@router.post("/space-data")
def build_space_data(body: SpaceDataRequest) -> dict:
    """사용자 마킹 확정 후 Agent 2 후반부 실행."""
    from app.api.pipeline import run_space_data
    user_dims = body.user_dims.model_dump() if body.user_dims else None
    return run_space_data(body.drawings, body.scale_mm_per_px, body.entrance_px, user_dims)


@router.post("/scale-correct")
def correct_scale(body: ScaleCorrection) -> dict:
    """사용자 수동 스케일 교정."""
    sx, sy = body.ref_start_px
    ex, ey = body.ref_end_px
    px_len = ((ex - sx) ** 2 + (ey - sy) ** 2) ** 0.5
    if px_len == 0:
        raise HTTPException(status_code=422, detail="시작점과 끝점이 동일합니다.")
    return {"scale_mm_per_px": body.actual_length_mm / px_len, "scale_confirmed": True}


@router.post("/placement")
def run_placement(body: PlacementRequest) -> dict:
    """전체 배치 파이프라인 실행."""
    from app.api.pipeline import run_placement_pipeline
    from app.core.exceptions import (
        RendyBaseError, LLMTimeoutError, LLMParsingError, LLMValidationError,
        ParserError, PlacementError, ExternalServiceError,
    )
    try:
        return run_placement_pipeline(body.drawings_json, body.brand_data, body.scale_mm_per_px)
    except Exception as e:
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


@router.post("/cache-save")
def cache_save(body: dict) -> dict:
    """세션 캐시 저장."""
    from app.api.cache_service import save_cache
    return save_cache(body)


@router.get("/cache-load")
def cache_load() -> dict:
    """세션 캐시 로드."""
    from app.api.cache_service import load_cache
    data = load_cache()
    if data is None:
        raise HTTPException(status_code=404, detail="캐시 없음")
    return data


@router.get("/objects")
def list_objects(brand_id: str = "sanrio") -> list:
    """오브젝트 목록 조회."""
    from app.api.object_crud import list_objects as _list
    return _list(brand_id)


@router.post("/objects")
def create_object(body: dict) -> dict:
    """오브젝트 추가."""
    from app.api.object_crud import create_object as _create
    return _create(body)


@router.put("/objects/{object_type}")
def update_object(object_type: str, body: dict) -> dict:
    """오브젝트 수정."""
    from app.api.object_crud import update_object as _update
    return _update(object_type, body)


@router.delete("/objects/{object_type}")
def delete_object(object_type: str, brand_id: str = "sanrio") -> dict:
    """오브젝트 삭제."""
    from app.api.object_crud import delete_object as _delete
    return _delete(object_type, brand_id)


@router.post("/brand")
async def extract_brand(
    brand_manual: UploadFile = File(..., description="브랜드 메뉴얼 PDF"),
) -> dict:
    """Agent 1 — 브랜드 메뉴얼 추출."""
    from app.agents.agent1_brand import extract
    pdf_bytes = await brand_manual.read()
    try:
        return extract(pdf_bytes)
    except Exception as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.post("/detect")
async def detect_floor_plan(
    floor_plan: UploadFile = File(..., description="평면도 파일"),
    section_drawing: UploadFile | None = File(None, description="단면도 파일 (선택)"),
) -> dict:
    """도면 감지 + PDF 미리보기."""
    from app.api.file_converter import generate_preview_with_viewport

    floor_bytes = await floor_plan.read()
    section_bytes = await section_drawing.read() if section_drawing else None
    filename = floor_plan.filename or ""

    parser = get_parser(filename=filename, floor_bytes=floor_bytes, section_bytes=section_bytes)
    try:
        result = await parser.parse()
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"도면 파싱 실패: {e}")

    response = result.model_dump()
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext in ("pdf", "dxf"):
        preview_b64, viewport = generate_preview_with_viewport(floor_bytes, ext)
        if preview_b64:
            response["preview_image_base64"] = preview_b64
        if viewport:
            response["dxf_viewport"] = viewport

    return response
