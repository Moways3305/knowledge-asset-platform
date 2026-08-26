"""Stable compatibility facade for decomposed upload-session workflows."""

from app.services.upload_session_creation import create_session, get_session_if_exists
from app.services.upload_session_recovery import (
    get_session,
    list_sessions,
    remove_failed_items,
    remove_item,
    retry_item,
)
from app.services.upload_session_repository import expire_stale_tasks
from app.services.upload_session_types import (
    BATCH_SIZE,
    MACOS_METADATA_MESSAGE,
    TRANSPORT_BATCH_MAX_BYTES,
    UNREADABLE_FILE_MESSAGE,
    UploadCandidate,
    authorize_create,
    extract_formed_on_from_filename,
    macos_metadata_error,
    stable_batch_sizes,
)
from app.services.upload_transport import (
    append_transport_batch,
    complete_transport_session,
    fail_transport_items,
    initialize_transport_session,
    preflight_transport_batch,
    replace_transport_item_bytes,
)

__all__ = [
    "BATCH_SIZE",
    "MACOS_METADATA_MESSAGE",
    "TRANSPORT_BATCH_MAX_BYTES",
    "UNREADABLE_FILE_MESSAGE",
    "UploadCandidate",
    "append_transport_batch",
    "authorize_create",
    "complete_transport_session",
    "create_session",
    "expire_stale_tasks",
    "extract_formed_on_from_filename",
    "fail_transport_items",
    "get_session",
    "get_session_if_exists",
    "initialize_transport_session",
    "list_sessions",
    "macos_metadata_error",
    "preflight_transport_batch",
    "remove_failed_items",
    "remove_item",
    "replace_transport_item_bytes",
    "retry_item",
    "stable_batch_sizes",
]
