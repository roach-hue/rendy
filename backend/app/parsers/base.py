from abc import ABC, abstractmethod
from app.schemas.drawings import ParsedDrawings


class FloorPlanParser(ABC):
    """
    파서 어댑터 추상 클래스.
    파일 형식(DXF/PDF/Image)에 관계없이 ParsedDrawings를 출력한다.
    Agent 2는 이 인터페이스만 사용 — 파일 형식 분기 금지. (claude.md 참조)
    """

    def __init__(self, floor_bytes: bytes, section_bytes: bytes | None = None):
        self.floor_bytes = floor_bytes
        self.section_bytes = section_bytes

    @abstractmethod
    async def parse(self) -> ParsedDrawings:
        """평면도(+ 단면도)를 파싱하여 ParsedDrawings 반환."""
        ...
