"""
P0-2 테스트 스크립트.
실행: cd backend && python test_p02.py <도면파일경로> [단면도파일경로]

결과를 콘솔에 출력하고 test_results/ 에 JSON으로 저장.
"""
import asyncio
import json
import sys
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")


async def run(floor_path: str, section_path: str | None = None):
    from app.parsers.factory import get_parser

    floor_bytes = Path(floor_path).read_bytes()
    section_bytes = Path(section_path).read_bytes() if section_path else None

    parser = get_parser(
        filename=Path(floor_path).name,
        floor_bytes=floor_bytes,
        section_bytes=section_bytes,
    )

    print(f"파서: {parser.__class__.__name__}")
    print(f"파일: {floor_path}")
    print("파싱 중...")

    result = await parser.parse()

    out = result.model_dump()

    print("\n=== 결과 ===")
    print(f"floor_polygon_px 꼭짓점 수: {len(out['floor_plan']['floor_polygon_px'])}")
    print(f"scale_mm_per_px: {out['floor_plan']['scale_mm_per_px']}")
    print(f"entrance: {out['floor_plan']['entrance']}")
    print(f"sprinklers: {len(out['floor_plan']['sprinklers'])}개")
    print(f"fire_hydrant: {len(out['floor_plan']['fire_hydrant'])}개")
    print(f"electrical_panel: {len(out['floor_plan']['electrical_panel'])}개")
    print(f"inner_walls: {len(out['floor_plan']['inner_walls'])}개")
    print(f"inaccessible_rooms: {len(out['floor_plan']['inaccessible_rooms'])}개")
    print(f"section (ceiling_height_mm): {out.get('section')}")

    out_dir = Path("test_results")
    out_dir.mkdir(exist_ok=True)
    out_file = out_dir / f"{Path(floor_path).stem}_result.json"
    out_file.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n결과 저장: {out_file}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("사용법: python test_p02.py <도면파일> [단면도파일]")
        sys.exit(1)
    asyncio.run(run(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None))
