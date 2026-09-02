"""Private, killable subprocess entry point for untrusted document parsing."""

from __future__ import annotations

import pickle
import sys

from app.services.extraction import _ControlledExtractionError, _extract_unbounded
from app.services.process_limits import apply_process_limits


def main() -> int:
    apply_process_limits()
    try:
        content, file_name, mime = pickle.loads(sys.stdin.buffer.read())
        result = _extract_unbounded(content, file_name=file_name, mime=mime)
        payload: tuple[str, object] = ("result", result)
    except _ControlledExtractionError as exc:
        payload = ("controlled", (exc.code, exc.message))
    except Exception:
        payload = ("failed", None)
    sys.stdout.buffer.write(pickle.dumps(payload, protocol=pickle.HIGHEST_PROTOCOL))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
