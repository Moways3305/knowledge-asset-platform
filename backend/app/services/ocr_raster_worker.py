"""Private, killable subprocess entry point for untrusted OCR rasterization."""

from __future__ import annotations

import io
import math
import pickle
import sys

from app.services.process_limits import apply_process_limits


class _RasterError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _rasterize(
    content: bytes, *, source_kind: str, page_number: int, max_image_pixels: int
) -> bytes:
    if source_kind == "image":
        from PIL import Image

        with Image.open(io.BytesIO(content)) as source:
            if source.width * source.height > max_image_pixels:
                raise _RasterError("ocr_structure_limit", "图片像素规模超过安全处理上限。")
            image = source.convert("RGB")
            out = io.BytesIO()
            image.save(out, format="PNG")
            return out.getvalue()

    import fitz

    document = fitz.open(stream=content, filetype="pdf")
    try:
        if page_number < 1 or page_number > document.page_count:
            raise _RasterError("ocr_source_invalid", "原文无法读取，OCR 未执行。")
        page = document.load_page(page_number - 1)
        matrix = fitz.Matrix(2, 2)
        raster_bounds = page.rect * matrix
        estimated_width = math.ceil(raster_bounds.x1) - math.floor(raster_bounds.x0)
        estimated_height = math.ceil(raster_bounds.y1) - math.floor(raster_bounds.y0)
        if estimated_width * estimated_height > max_image_pixels:
            raise _RasterError("ocr_structure_limit", "页面像素规模超过安全处理上限。")
        pixmap = page.get_pixmap(matrix=matrix, alpha=False)
        if pixmap.width * pixmap.height > max_image_pixels:
            raise _RasterError("ocr_structure_limit", "页面像素规模超过安全处理上限。")
        return bytes(pixmap.tobytes("png"))
    finally:
        document.close()


def main() -> int:
    apply_process_limits()
    try:
        content, source_kind, page_number, max_image_pixels = pickle.loads(sys.stdin.buffer.read())
        payload: tuple[str, object] = (
            "result",
            _rasterize(
                content,
                source_kind=source_kind,
                page_number=page_number,
                max_image_pixels=max_image_pixels,
            ),
        )
    except _RasterError as exc:
        payload = ("controlled", (exc.code, exc.message))
    except Exception:
        payload = ("failed", None)
    sys.stdout.buffer.write(pickle.dumps(payload, protocol=pickle.HIGHEST_PROTOCOL))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
