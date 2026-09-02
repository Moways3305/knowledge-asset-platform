"""Private, killable subprocess entry point for untrusted document parsing."""

from __future__ import annotations

import pickle
import sys

from app.services.extraction import _ControlledExtractionError, _extract_unbounded

MAX_ADDRESS_SPACE_BYTES = 768 * 1024 * 1024
MAX_CPU_SECONDS = 60


def _apply_process_limits() -> None:
    """Best-effort kernel limits on Unix; parent wall clock remains authoritative."""
    try:
        import resource

        resource.setrlimit(resource.RLIMIT_AS, (MAX_ADDRESS_SPACE_BYTES, MAX_ADDRESS_SPACE_BYTES))
        resource.setrlimit(resource.RLIMIT_CPU, (MAX_CPU_SECONDS, MAX_CPU_SECONDS))
    except (ImportError, OSError, ValueError):
        # Windows and restricted containers lack resource(2). Structural limits,
        # the parent kill timeout, and the Celery hard limit still apply there.
        return


def main() -> int:
    _apply_process_limits()
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
