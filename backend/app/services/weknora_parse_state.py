"""Provider parse states shared by ingestion, reconciliation and diagnostics.

WeKnora v0.9.0 keeps enrichment work in ``finalizing`` before ``completed``.
Cancelled parsing retains its document but requires an explicit retry.
"""

PENDING_PARSE_STATUSES = frozenset({"pending", "processing", "finalizing"})
FAILED_PARSE_STATUSES = frozenset({"failed", "cancelled", "canceled"})
TERMINAL_PARSE_STATUSES = FAILED_PARSE_STATUSES | {"completed", "duplicate"}


def parse_error_code(status: str | None) -> str:
    return (
        "weknora_parse_cancelled" if status in {"cancelled", "canceled"} else "weknora_parse_failed"
    )
