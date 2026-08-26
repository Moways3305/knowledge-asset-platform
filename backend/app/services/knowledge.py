"""Stable facade for decomposed knowledge queries, projections, and commands."""

from app.services.knowledge_catalog import (
    get_detail,
    list_directories,
    list_knowledge,
    list_knowledge_library_projects,
)
from app.services.knowledge_index_commands import delete_asset, retry_index
from app.services.knowledge_personal_query import list_my_knowledge
from app.services.knowledge_projection import (
    _build_access_info,
    _select_summary_text,
    _summary_map,
    can_retry_index,
)

__all__ = [
    "_build_access_info",
    "_select_summary_text",
    "_summary_map",
    "can_retry_index",
    "delete_asset",
    "get_detail",
    "list_directories",
    "list_knowledge",
    "list_knowledge_library_projects",
    "list_my_knowledge",
    "retry_index",
]
