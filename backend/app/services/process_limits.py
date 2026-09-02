"""Best-effort resource limits shared by killable parser subprocesses."""

from __future__ import annotations

MAX_ADDRESS_SPACE_BYTES = 768 * 1024 * 1024
MAX_CPU_SECONDS = 60


def apply_process_limits() -> None:
    """Apply kernel limits on Unix; the parent wall clock remains authoritative."""
    try:
        import resource

        resource.setrlimit(resource.RLIMIT_AS, (MAX_ADDRESS_SPACE_BYTES, MAX_ADDRESS_SPACE_BYTES))
        resource.setrlimit(resource.RLIMIT_CPU, (MAX_CPU_SECONDS, MAX_CPU_SECONDS))
    except (ImportError, OSError, ValueError):
        # Windows and restricted containers lack resource(2). Structural limits,
        # the parent kill timeout, and the Celery hard limit still apply there.
        return
