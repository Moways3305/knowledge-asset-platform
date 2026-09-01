"""First-party browser workbench API."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_caller_context
from app.db.session import get_db
from app.schemas.permission import CallerContext
from app.schemas.workbench import WorkbenchOverviewResponse
from app.services import workbench as workbench_service
from app.services.storage import LocalFileStorage, get_storage

router = APIRouter(prefix="/api/v1/workbench", tags=["workbench"])


@router.get("/overview", response_model=WorkbenchOverviewResponse)
async def get_workbench_overview(
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
    storage: LocalFileStorage = Depends(get_storage),
) -> WorkbenchOverviewResponse:
    """Return a session-bound, permission-filtered workbench overview."""
    return await workbench_service.get_overview(session, caller, storage=storage)
