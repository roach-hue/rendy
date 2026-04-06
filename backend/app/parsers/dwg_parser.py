"""
DWG 도면 파서 — ODA File Converter로 DXF 변환 후 DXFParser 위임.

ODA File Converter 필요:
  https://www.opendesign.com/guestfiles/oda_file_converter
  설치 후 ODA_CONVERTER_PATH 환경변수에 실행 파일 경로 설정.
  예: ODA_CONVERTER_PATH=C:/Program Files/ODA/ODAFileConverter/ODAFileConverter.exe

주의: ODA는 비상업용 무료. 상업용 서버에서는 라이선스 확인 필요.
"""
import os
import subprocess
import tempfile
from pathlib import Path

from app.parsers.base import FloorPlanParser
from app.parsers.dxf_parser import DXFParser
from app.schemas.drawings import ParsedDrawings


# ODA 실행 파일 경로 (환경변수 또는 기본값)
ODA_PATH = os.getenv(
    "ODA_CONVERTER_PATH",
    "C:/Program Files/ODA/ODAFileConverter/ODAFileConverter.exe",
)


class DWGParser(FloorPlanParser):
    """DWG → ODA로 DXF 변환 → DXFParser 위임."""

    async def parse(self) -> ParsedDrawings:
        if not Path(ODA_PATH).exists():
            raise FileNotFoundError(
                f"ODA File Converter가 설치되지 않았습니다. "
                f"경로: {ODA_PATH}\n"
                f"설치: https://www.opendesign.com/guestfiles/oda_file_converter\n"
                f"설치 후 환경변수 ODA_CONVERTER_PATH에 실행 파일 경로를 설정하세요."
            )

        dxf_bytes = _convert_dwg_to_dxf(self.floor_bytes)
        section_dxf = None
        if self.section_bytes:
            section_dxf = _convert_dwg_to_dxf(self.section_bytes)

        dxf_parser = DXFParser(dxf_bytes, section_dxf)
        return await dxf_parser.parse()


def _convert_dwg_to_dxf(dwg_bytes: bytes) -> bytes:
    """ODA File Converter로 DWG → DXF 변환."""
    with tempfile.TemporaryDirectory() as tmpdir:
        input_dir = Path(tmpdir) / "input"
        output_dir = Path(tmpdir) / "output"
        input_dir.mkdir()
        output_dir.mkdir()

        # DWG 파일 저장
        dwg_file = input_dir / "drawing.dwg"
        dwg_file.write_bytes(dwg_bytes)

        # ODA 호출: input_dir → output_dir, DXF 2018 버전, 감사(Audit) 활성화
        result = subprocess.run(
            [ODA_PATH, str(input_dir), str(output_dir), "ACAD2018", "DXF", "0", "1"],
            capture_output=True, text=True, timeout=60,
        )

        if result.returncode != 0:
            raise RuntimeError(f"ODA 변환 실패: {result.stderr or result.stdout}")

        # 변환된 DXF 파일 읽기
        dxf_files = list(output_dir.glob("*.dxf"))
        if not dxf_files:
            raise RuntimeError("ODA 변환 완료했으나 DXF 파일이 생성되지 않았습니다.")

        dxf_bytes = dxf_files[0].read_bytes()
        print(f"[DWGParser] converted: {len(dwg_bytes)} bytes DWG → {len(dxf_bytes)} bytes DXF")
        return dxf_bytes
