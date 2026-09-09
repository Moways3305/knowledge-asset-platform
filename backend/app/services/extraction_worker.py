"""Private, killable subprocess entry point for untrusted document parsing."""

from __future__ import annotations

import os
import pickle
import sys

from app.services.extraction import _ControlledExtractionError, _extract_unbounded
from app.services.process_limits import apply_process_limits


def _run(output) -> int:
    apply_process_limits()
    try:
        content, file_name, mime = pickle.loads(sys.stdin.buffer.read())
        result = _extract_unbounded(content, file_name=file_name, mime=mime)
        payload: tuple[str, object] = ("result", result)
    except _ControlledExtractionError as exc:
        payload = ("controlled", (exc.code, exc.message))
    except MemoryError:
        payload = (
            "controlled",
            (
                "extraction_memory_limit",
                "文件解析达到内存限制，原件已保留；请管理员检查资源，或拆分文件后重试。",
            ),
        )
    except Exception:
        payload = ("failed", None)
    output.write(pickle.dumps(payload, protocol=pickle.HIGHEST_PROTOCOL))
    return 0


def main() -> int:
    sys.stdout.flush()
    with os.fdopen(os.dup(sys.stdout.fileno()), "wb") as output:
        os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
        return _run(output)


if __name__ == "__main__":
    raise SystemExit(main())
