"""Killable one-page renderer invoked by app.services.ocr."""

from __future__ import annotations

import io
import os
import sys


def _render(output) -> int:
    source_kind, page_raw, max_pixels_raw = sys.argv[1:4]
    page_number = int(page_raw)
    max_pixels = int(max_pixels_raw)
    content = sys.stdin.buffer.read()
    try:
        if source_kind == "image":
            from PIL import Image

            with Image.open(io.BytesIO(content)) as source:
                if source.width * source.height > max_pixels:
                    return 3
                image = source.convert("RGB")
                out = io.BytesIO()
                image.save(out, format="PNG")
                output.write(out.getvalue())
                return 0
        import pymupdf as fitz

        document = fitz.open(stream=content, filetype="pdf")
        try:
            if page_number < 1 or page_number > document.page_count:
                return 2
            page = document.load_page(page_number - 1)
            if int(page.rect.width * 2) * int(page.rect.height * 2) > max_pixels:
                return 3
            output.write(page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False).tobytes("png"))
            return 0
        finally:
            document.close()
    except Exception:
        return 2


def main() -> int:
    # Reserve the binary protocol channel before loading any rendering library.
    # Redirect both Python prints and native-library stdout diagnostics to stderr.
    sys.stdout.flush()
    with os.fdopen(os.dup(sys.stdout.fileno()), "wb") as output:
        os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
        return _render(output)


if __name__ == "__main__":
    raise SystemExit(main())
