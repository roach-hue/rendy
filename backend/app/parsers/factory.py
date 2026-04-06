from app.parsers.base import FloorPlanParser


def get_parser(
    filename: str,
    floor_bytes: bytes,
    section_bytes: bytes | None = None,
) -> FloorPlanParser:
    """
    파일 확장자로 파서 어댑터를 선택.
    Agent 2 코드는 이 함수만 호출 — 형식 분기 로직을 여기에만 둔다.
    """
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    if ext == "dxf":
        from app.parsers.dxf_parser import DXFParser
        return DXFParser(floor_bytes, section_bytes)

    if ext == "dwg":
        from app.parsers.dwg_parser import DWGParser
        return DWGParser(floor_bytes, section_bytes)

    if ext == "pdf":
        from app.parsers.pdf_parser import PDFParser
        return PDFParser(floor_bytes, section_bytes)

    if ext in ("png", "jpg", "jpeg", "webp", "tiff", "bmp"):
        from app.parsers.image_parser import ImageParser
        return ImageParser(floor_bytes, section_bytes)

    raise ValueError(f"지원하지 않는 파일 형식: .{ext}  (DXF / PDF / 이미지만 허용)")
