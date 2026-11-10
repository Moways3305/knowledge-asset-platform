"""Project QA must not hold PostgreSQL connections across slow model calls."""

import asyncio

import pytest
import test_search_pool_postgres as pool_tests
from fastapi import HTTPException
from sqlalchemy import func, select, text
from test_search_api import KA_ALPHA_L4, FakeSearchWeKnora

from app.models.agent import (
    AgentCall,
    AgentCallCitation,
    AgentGatewayDecision,
    AgentGatewayDecisionItem,
)
from app.models.audit import AuditEvent
from app.models.auth_session import UserSession
from app.models.identity import ProjectMember, User, UserCompanyRole
from app.models.knowledge import KnowledgeAsset, KnowledgeAssetVersion
from app.schemas.agent import ProjectQaRequest
from app.seed.dev_seed import PROJECT_ALPHA, USER_CONSULTANT
from app.services import agent, auth_session
from app.services.identity import load_user_with_roles
from app.services.llm_client import LLMError
from app.services.permission import build_caller_context

single_connection_db = pool_tests.single_connection_db


@pytest.mark.parametrize("stage", ["planning", "recall", "scrub", "answer"])
@pytest.mark.parametrize("cancel", [False, True])
async def test_project_qa_releases_pool_throughout_model_calls(single_connection_db, stage, cancel):
    sessions = single_connection_db
    entered, release = asyncio.Event(), asyncio.Event()

    async def hold(current):
        if stage == current:
            entered.set()
            await release.wait()

    class Model:
        provider = "test"
        model = "synthetic"

        async def chat_completion(self, messages, **kwargs):
            system = messages[0]["content"]
            if '"queries"' in system:
                await hold("planning")
                return '{"queries":[]}'
            if "脱敏" in system:
                await hold("scrub")
                return "合成脱敏后的交付方法：先调查，再核验。"
            await hold("answer")
            return '{"status":"answered","answer":"合成交付方法。[1]","citation_orders":[1]}'

    class Recall(FakeSearchWeKnora):
        async def search(self, **kwargs):
            await hold("recall")
            return await super().search(**kwargs)

    async with sessions() as session:
        user = await load_user_with_roles(session, user_id=USER_CONSULTANT)
        token = await auth_session.create_session(session, user)
        await session.commit()
        user = await auth_session.resolve_session_user(session, token)
        heartbeat = await session.scalar(select(UserSession))
        seen_at = heartbeat.last_seen_at
        caller = build_caller_context(user)
        pending = asyncio.create_task(
            agent.run_project_qa(
                session,
                caller,
                PROJECT_ALPHA,
                ProjectQaRequest(query="合成项目问答"),
                "synthetic-qa-pool",
                weknora=Recall(
                    [
                        {
                            "knowledge_id": f"wk-doc-{KA_ALPHA_L4}",
                            "kb_id": f"wk-kb-proj-{PROJECT_ALPHA}",
                            "content": "合成交付方法，先调查再核验。",
                        }
                    ]
                ),
                llm=Model(),
            )
        )
        try:
            await asyncio.wait_for(entered.wait(), 5)
            async with sessions() as other:
                assert await asyncio.wait_for(other.scalar(text("SELECT 1")), 0.75) == 1
                # No partial call/decision/audit is published while awaiting a model.
                assert await other.scalar(select(func.count()).select_from(AgentCall)) == 0
            if cancel:
                pending.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await pending
            else:
                release.set()
                result = await asyncio.wait_for(pending, 5)
                assert result.answer_status == "answered"
                assert [citation.asset_id for citation in result.citations] == [KA_ALPHA_L4]
        finally:
            release.set()
            if not pending.done():
                pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
    async with sessions() as check:
        for model in (AgentCall, AgentGatewayDecision, AgentGatewayDecisionItem, AgentCallCitation):
            assert await check.scalar(select(func.count()).select_from(model)) == (
                0 if cancel else 1
            )
        actions = list(
            await check.scalars(
                select(AuditEvent.action).where(AuditEvent.trace_id == "synthetic-qa-pool")
            )
        )
        assert sorted(actions) == ([] if cancel else ["agent.allowed", "agent.called"])
        assert (await check.scalar(select(UserSession))).last_seen_at == seen_at


class ControlledModel:
    provider = "test"
    model = "synthetic"

    def __init__(self, stage=None, fail=False):
        self.stage, self.fail = stage, fail
        self.entered, self.release = asyncio.Event(), asyncio.Event()

    async def chat_completion(self, messages, **kwargs):
        system = messages[0]["content"]
        stage = "planning" if '"queries"' in system else "scrub" if "脱敏" in system else "answer"
        if stage == self.stage:
            self.entered.set()
            await self.release.wait()
        if stage == "planning":
            return '{"queries":[]}'
        if stage == "scrub":
            return "合成脱敏内容。"
        if self.fail:
            raise LLMError("external_llm_unavailable", "synthetic-private-upstream-detail")
        return '{"status":"answered","answer":"合成结论。[1]","citation_orders":[1]}'


async def request_qa(session, model, *, documents=True):
    user = await load_user_with_roles(session, user_id=USER_CONSULTANT)
    return await agent.run_project_qa(
        session,
        build_caller_context(user),
        PROJECT_ALPHA,
        ProjectQaRequest(query="合成项目问答"),
        "synthetic-qa-outcome",
        llm=model,
        weknora=FakeSearchWeKnora(
            [
                {
                    "knowledge_id": f"wk-doc-{KA_ALPHA_L4}",
                    "kb_id": f"wk-kb-proj-{PROJECT_ALPHA}",
                    "content": "合成资料内容。",
                }
            ]
            if documents
            else []
        ),
    )


async def assert_no_partial_outcome(sessions, *, denied=False):
    async with sessions() as check:
        for model in (AgentCall, AgentGatewayDecision, AgentGatewayDecisionItem, AgentCallCitation):
            assert await check.scalar(select(func.count()).select_from(model)) == 0
        actions = list(
            await check.scalars(
                select(AuditEvent.action).where(AuditEvent.trace_id == "synthetic-qa-outcome")
            )
        )
        assert actions == (["agent.denied"] if denied else [])
        assert await check.scalar(text("SELECT 1")) == 1


async def test_project_qa_timeout_leaves_no_partial_outcome(single_connection_db):
    sessions = single_connection_db
    model = ControlledModel("answer")
    async with sessions() as session:
        pending = asyncio.create_task(request_qa(session, model))
        try:
            await asyncio.wait_for(model.entered.wait(), 5)
            with pytest.raises(asyncio.TimeoutError):
                await asyncio.wait_for(pending, 0.05)
            assert not session.in_transaction()
        finally:
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
    await assert_no_partial_outcome(sessions)


@pytest.mark.parametrize("documents", [True, False])
async def test_project_qa_expected_denials_commit_complete_audit(single_connection_db, documents):
    sessions = single_connection_db
    async with sessions() as session:
        with pytest.raises(HTTPException) as denied:
            await request_qa(session, ControlledModel(fail=True), documents=documents)
        assert denied.value.status_code == (503 if documents else 403)
        assert not session.in_transaction()
    async with sessions() as check:
        call = await check.scalar(select(AgentCall))
        assert call.call_status == "denied"
        assert call.response_text is None
        decision = await check.scalar(select(AgentGatewayDecision))
        assert decision.call_id == call.id
        assert decision.denied_reason == call.denied_reason
        assert await check.scalar(
            select(func.count()).select_from(AgentGatewayDecisionItem)
        ) == int(documents)
        assert await check.scalar(select(func.count()).select_from(AgentCallCitation)) == 0
        actions = list(
            await check.scalars(
                select(AuditEvent.action).where(AuditEvent.trace_id == "synthetic-qa-outcome")
            )
        )
        assert sorted(actions) == ["agent.called", "agent.denied"]


@pytest.mark.parametrize("cancel", [False, True])
async def test_final_write_failure_rolls_back_all_records(
    single_connection_db, monkeypatch, cancel
):
    sessions = single_connection_db
    entered = asyncio.Event()
    record = agent.audit_service.record_event

    async def fail_at_final_audit(session, **kwargs):
        event = await record(session, **kwargs)
        if kwargs["action"] == "agent.allowed":
            await session.flush()  # Force all four tables + audit into the transaction.
            entered.set()
            if cancel:
                await asyncio.Event().wait()
            raise RuntimeError("synthetic final write failure")
        return event

    monkeypatch.setattr(agent.audit_service, "record_event", fail_at_final_audit)
    async with sessions() as session:
        pending = asyncio.create_task(request_qa(session, ControlledModel()))
        try:
            await asyncio.wait_for(entered.wait(), 5)
            if cancel:
                pending.cancel()
            with pytest.raises(asyncio.CancelledError if cancel else RuntimeError):
                await pending
            assert not session.in_transaction()
        finally:
            if not pending.done():
                pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
    await assert_no_partial_outcome(sessions)


@pytest.mark.parametrize("stage", ["scrub", "answer"])
@pytest.mark.parametrize(
    "change", ["membership", "company_role", "user", "delete", "a4", "version"]
)
async def test_concurrent_revocation_or_edit_rejects_stale_answer(
    single_connection_db, stage, change
):
    sessions = single_connection_db
    model = ControlledModel(stage)
    if change == "company_role":
        async with sessions() as writer:
            writer.add(UserCompanyRole(user_id=USER_CONSULTANT, company_role="boss"))
            await writer.commit()
    async with sessions() as session:
        pending = asyncio.create_task(request_qa(session, model))
        try:
            await asyncio.wait_for(model.entered.wait(), 5)
            async with sessions() as writer:
                if change == "membership":
                    row = await writer.scalar(
                        select(ProjectMember).where(
                            ProjectMember.project_id == PROJECT_ALPHA,
                            ProjectMember.user_id == USER_CONSULTANT,
                        )
                    )
                    row.status = "inactive"
                elif change == "company_role":
                    role = await writer.scalar(
                        select(UserCompanyRole).where(
                            UserCompanyRole.user_id == USER_CONSULTANT,
                            UserCompanyRole.company_role == "boss",
                        )
                    )
                    role.status = "inactive"
                elif change == "user":
                    (await writer.get(User, USER_CONSULTANT)).status = "inactive"
                elif change == "version":
                    row = await writer.scalar(
                        select(KnowledgeAssetVersion).where(
                            KnowledgeAssetVersion.asset_id == KA_ALPHA_L4,
                        )
                    )
                    row.index_status = "failed"
                else:
                    row = await writer.get(KnowledgeAsset, KA_ALPHA_L4)
                    if change == "delete":
                        row.asset_status = "deleted"
                    else:
                        row.ai_access_level = "A4"
                await writer.commit()
            model.release.set()
            with pytest.raises(HTTPException) as denied:
                await asyncio.wait_for(pending, 5)
            assert denied.value.status_code == 409
            assert denied.value.detail["denied_reason"] == "qa_context_changed"
        finally:
            model.release.set()
            if not pending.done():
                pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
    await assert_no_partial_outcome(sessions, denied=True)
