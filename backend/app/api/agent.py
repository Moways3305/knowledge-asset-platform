"""Agent / Dify Gateway API。

- POST /api/v1/projects/{project_id}/qa：项目 Q&A，经平台权限网关生成安全回答与引用。
- GET  /api/v1/agent-calls/{call_id}：获取调用记录（本人 / boss / 咨询总监）。
- GET  /api/v1/agent-calls/{call_id}/decision-items：候选项决策明细（治理解释）。

权限判断全部委托 `app.services.agent`（其内部复用集中权限服务，channel=agent）。
不接真实 Dify，使用 internal_stub provider；响应不含任何 Dify / 对象存储 / 向量库内部标识。
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_caller_context
from app.core.trace import get_trace_id
from app.db.session import get_db
from app.schemas.agent import (
    AgentCallDetailResponse,
    DecisionItemsResponse,
    ProjectQaRequest,
    ProjectQaResponse,
)
from app.schemas.permission import CallerContext
from app.services import agent as agent_service
from app.services.llm_client import get_llm_client
from app.services.weknora_client import get_weknora_client

router = APIRouter(prefix="/api/v1", tags=["agent"])


@router.post("/projects/{project_id}/qa", response_model=ProjectQaResponse)
async def project_qa(
    project_id: uuid.UUID,
    req: ProjectQaRequest,
    request: Request,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
    weknora=Depends(get_weknora_client),
    llm=Depends(get_llm_client),
) -> ProjectQaResponse:
    return await agent_service.run_project_qa(
        session, caller, project_id, req, get_trace_id(request), weknora=weknora, llm=llm
    )


@router.get("/agent-calls/{call_id}", response_model=AgentCallDetailResponse)
async def get_agent_call(
    call_id: uuid.UUID,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
) -> AgentCallDetailResponse:
    return await agent_service.get_agent_call(session, caller, call_id)


@router.get(
    "/agent-calls/{call_id}/decision-items", response_model=DecisionItemsResponse
)
async def get_decision_items(
    call_id: uuid.UUID,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
) -> DecisionItemsResponse:
    return await agent_service.get_decision_items(session, caller, call_id)

