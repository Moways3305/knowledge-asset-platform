"""Read-only selectors for administrative operations."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_caller_context
from app.db.session import get_db
from app.schemas.operation_options import OperationProjectOptions, OperationUserOptions
from app.schemas.permission import CallerContext
from app.services import operation_options

router = APIRouter(prefix="/api/v1/admin/operation-options", tags=["operation-options"])


@router.get("/projects", response_model=OperationProjectOptions)
async def projects(
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
) -> OperationProjectOptions:
    return await operation_options.list_projects(session, caller)


@router.get("/users", response_model=OperationUserOptions)
async def users(
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
) -> OperationUserOptions:
    return await operation_options.list_users(session, caller)
