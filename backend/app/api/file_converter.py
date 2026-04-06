"""파일 변환 — PDF/DXF 미리보기 래스터화."""
import base64
import io
import os
import tempfile


def generate_preview(file_bytes: bytes, ext: str) -> str | None:
    """PDF/DXF → 첫 페이지 PNG 래스터화 → base64."""
    try:
        if ext == "pdf":
            return _preview_pdf(file_bytes)
        if ext == "dxf":
            result = _preview_dxf(file_bytes)
            return result[0] if result else None
    except Exception as e:
        print(f"[Preview] failed: {e}")
    return None


def generate_preview_with_viewport(file_bytes: bytes, ext: str) -> tuple[str | None, dict | None]:
    """
    DXF → (preview_base64, viewport_dict).
    preview와 viewport가 동일한 geometry BBox를 기준으로 생성됨을 보장.
    PDF/이미지 → (preview_base64, None).
    """
    try:
        if ext == "pdf":
            return _preview_pdf(file_bytes), None
        if ext == "dxf":
            result = _preview_dxf(file_bytes)
            if result:
                return result
            return None, None
    except Exception as e:
        print(f"[Preview] failed: {e}")
    return None, None


def _preview_pdf(file_bytes: bytes) -> str | None:
    """PDF → PNG (PyMuPDF 150 DPI)."""
    import fitz
    doc = fitz.open(stream=file_bytes, filetype="pdf")
    page = doc[0]
    pix = page.get_pixmap(matrix=fitz.Matrix(150 / 72, 150 / 72), alpha=False)
    png_bytes = pix.tobytes("png")
    print(f"[Preview] PDF → PNG: {len(png_bytes)} bytes")
    return base64.b64encode(png_bytes).decode()


# matplotlib 렌더링 마진 (geometry BBox 대비 %)
# 도면 가장자리 선이 이미지 경계에 딱 붙지 않도록 약간의 여백
_MARGIN_RATIO = 0.03


def _preview_dxf(file_bytes: bytes) -> tuple[str, dict] | None:
    """
    DXF → (PNG base64, viewport dict).

    핵심: geometry-only BBox로 axis limits를 명시적으로 설정.
    - TEXT/MTEXT 제외 → floor polygon 기준 렌더링 영역
    - pad_inches=0 → matplotlib 패딩 불확정 요소 제거
    - 마진은 _MARGIN_RATIO로 직접 제어
    - viewport는 마진 포함 최종 axis limits를 반환
    """
    import ezdxf
    from ezdxf.addons.drawing import Frontend, RenderContext
    from ezdxf.addons.drawing.matplotlib import MatplotlibBackend
    from ezdxf.addons.drawing.properties import LayoutProperties
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    doc = _read_dxf(file_bytes)
    msp = doc.modelspace()

    # 전체 엔티티 BBox (TEXT 포함 — 렌더링에서 잘리지 않도록)
    all_bounds = _all_entity_bounds(msp)
    if not all_bounds:
        return None

    min_x, min_y, max_x, max_y = all_bounds
    vw = max_x - min_x
    vh = max_y - min_y

    # 마진 추가
    mx = vw * _MARGIN_RATIO
    my = vh * _MARGIN_RATIO
    view_min_x = min_x - mx
    view_min_y = min_y - my
    view_max_x = max_x + mx
    view_max_y = max_y + my

    # matplotlib 렌더링
    final_vw = view_max_x - view_min_x
    final_vh = view_max_y - view_min_y
    dpi = 150

    fig = plt.figure(dpi=dpi)
    ax = fig.add_axes([0, 0, 1, 1])

    ctx = RenderContext(doc)
    layout_props = LayoutProperties.from_layout(msp)
    layout_props.set_colors(bg="#FFFFFF", fg="#000000")

    out = MatplotlibBackend(ax)
    Frontend(ctx, out).draw_layout(msp, layout_properties=layout_props)

    # ezdxf 렌더링 후 axis limits + figure 크기 강제 세팅
    ax.set_xlim(view_min_x, view_max_x)
    ax.set_ylim(view_min_y, view_max_y)
    ax.set_aspect("auto")
    ax.set_facecolor("white")
    ax.axis("off")

    # figure 크기를 viewport 비율에 맞춰 강제 (ezdxf가 바꿨을 수 있으므로)
    target_w_inch = 8.0
    target_h_inch = target_w_inch * (final_vh / final_vw) if final_vw > 0 else target_w_inch
    fig.set_size_inches(target_w_inch, target_h_inch)
    fig.subplots_adjust(left=0, right=1, top=1, bottom=0)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi,
                facecolor="white", pad_inches=0)
    plt.close(fig)

    png_bytes = buf.getvalue()
    print(f"[Preview] DXF → PNG: {len(png_bytes)} bytes, "
          f"viewport=({view_min_x:.0f},{view_min_y:.0f})→({view_max_x:.0f},{view_max_y:.0f})")

    viewport = {
        "min_x": round(float(view_min_x), 1),
        "min_y": round(float(view_min_y), 1),
        "max_x": round(float(view_max_x), 1),
        "max_y": round(float(view_max_y), 1),
    }

    return base64.b64encode(png_bytes).decode(), viewport


def _all_entity_bounds(msp) -> tuple[float, float, float, float] | None:
    """전체 엔티티(TEXT 포함) BBox. 렌더링 viewport 용."""
    all_x: list[float] = []
    all_y: list[float] = []

    for entity in msp:
        try:
            dtype = entity.dxftype()
            if dtype == "LINE":
                all_x.extend([entity.dxf.start.x, entity.dxf.end.x])
                all_y.extend([entity.dxf.start.y, entity.dxf.end.y])
            elif dtype == "LWPOLYLINE":
                for p in entity.get_points():
                    all_x.append(p[0])
                    all_y.append(p[1])
            elif dtype in ("ARC", "CIRCLE"):
                cx, cy = entity.dxf.center.x, entity.dxf.center.y
                r = entity.dxf.radius
                all_x.extend([cx - r, cx + r])
                all_y.extend([cy - r, cy + r])
            elif dtype in ("TEXT", "MTEXT"):
                ins = entity.dxf.insert
                all_x.append(ins.x)
                all_y.append(ins.y)
        except Exception:
            continue

    if not all_x:
        return None
    return min(all_x), min(all_y), max(all_x), max(all_y)


def _geometry_only_bounds(msp) -> tuple[float, float, float, float] | None:
    """
    기하학 엔티티(LINE, LWPOLYLINE, ARC, CIRCLE)만의 BBox.
    TEXT/MTEXT 제외 — floor polygon 기준 렌더링 영역.
    """
    all_x: list[float] = []
    all_y: list[float] = []

    for entity in msp:
        try:
            dtype = entity.dxftype()
            if dtype == "LINE":
                all_x.extend([entity.dxf.start.x, entity.dxf.end.x])
                all_y.extend([entity.dxf.start.y, entity.dxf.end.y])
            elif dtype == "LWPOLYLINE":
                for p in entity.get_points():
                    all_x.append(p[0])
                    all_y.append(p[1])
            elif dtype in ("ARC", "CIRCLE"):
                cx, cy = entity.dxf.center.x, entity.dxf.center.y
                r = entity.dxf.radius
                all_x.extend([cx - r, cx + r])
                all_y.extend([cy - r, cy + r])
            # TEXT, MTEXT → 의도적 제외
        except Exception:
            continue

    if not all_x:
        return None

    return min(all_x), min(all_y), max(all_x), max(all_y)


def _read_dxf(file_bytes: bytes):
    """bytes → ezdxf Document (임시 파일 경유)."""
    import ezdxf
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".dxf")
    try:
        with os.fdopen(tmp_fd, "wb") as f:
            f.write(file_bytes)
        return ezdxf.readfile(tmp_path)
    finally:
        os.unlink(tmp_path)
