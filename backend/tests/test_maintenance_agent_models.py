"""Selected Agent models must reach execution and never silently fall back."""

import pytest
from sqlalchemy import select
from test_generation_models import _create
from test_maintenance_agent import content_asset, headers, run_asset

from app.models.generation_model import ContentGenerationModel
from app.models.maintenance_agent import MaintenancePolicy, MaintenanceRun
from app.services import generation_models
from app.services.llm_client import LLMClient, NullLLMClient
from app.services.maintenance_jobs import process_one


async def models(client):
    default = await _create(client, display_name="平台默认", model_name="default-model")
    explicit = await _create(
        client, display_name="巡检专用", model_name="agent-model", make_default=False
    )
    assert default.status_code == explicit.status_code == 201
    return default.json(), explicit.json()


async def configure_model(client, model_ref, revision=0):
    return await client.put(
        "/api/v1/maintenance-agent/policies/company",
        headers=headers(),
        json={
            "expected_revision": revision,
            "content_authorized": True,
            "settings": {"model_ref": model_ref},
        },
    )


async def test_selected_model_is_saved_and_used_by_worker(
    client, sessionmaker_fixture, tmp_path, monkeypatch
):
    _, selected = await models(client)
    configured = await configure_model(client, selected["model_ref"])
    assert configured.status_code == 200, configured.text
    assert configured.json()["settings"]["model_ref"] == selected["model_ref"]
    calls = []

    async def complete(self, messages, **kwargs):
        calls.append(self.model)
        return '{"complete":true,"findings":[]}'

    monkeypatch.setattr(LLMClient, "chat_completion", complete)
    asset, storage = await content_asset(sessionmaker_fixture, tmp_path)
    await run_asset(sessionmaker_fixture, asset)
    assert await process_one(sessionmaker_fixture, storage=storage)
    assert calls == ["agent-model"]


@pytest.mark.parametrize("change", ["disabled", "deleted", "wrong_capability", "unreadable_secret"])
async def test_unavailable_selection_never_falls_back_to_healthy_default(
    client, sessionmaker_fixture, change
):
    _, selected = await models(client)
    async with sessionmaker_fixture() as session:
        row = await session.scalar(
            select(ContentGenerationModel).where(ContentGenerationModel.model_name == "agent-model")
        )
        if change == "disabled":
            row.enabled = False
        elif change == "deleted":
            await session.delete(row)
        elif change == "wrong_capability":
            row.capability_type = "embedding"
        else:
            row.api_key_ciphertext = "unreadable"
        await session.commit()
        assert isinstance(
            await generation_models.resolve_generation_llm_client(
                session, model_ref=selected["model_ref"]
            ),
            NullLLMClient,
        )
        default = await generation_models.resolve_generation_llm_client(session)
        assert isinstance(default, LLMClient) and default.model == "default-model"


async def test_disabled_model_does_not_reuse_previous_quality_check(
    client, sessionmaker_fixture, tmp_path, monkeypatch
):
    _, selected = await models(client)
    assert (await configure_model(client, selected["model_ref"])).status_code == 200
    calls = []

    async def complete(self, messages, **kwargs):
        calls.append(self.model)
        return '{"complete":true,"findings":[]}'

    monkeypatch.setattr(LLMClient, "chat_completion", complete)
    asset, storage = await content_asset(sessionmaker_fixture, tmp_path)
    await run_asset(sessionmaker_fixture, asset)
    await process_one(sessionmaker_fixture, storage=storage)
    await process_one(sessionmaker_fixture, storage=storage)
    async with sessionmaker_fixture() as session:
        row = await session.scalar(
            select(ContentGenerationModel).where(ContentGenerationModel.model_name == "agent-model")
        )
        row.enabled = False
        await session.commit()
    run_id = await run_asset(sessionmaker_fixture, asset, kind="incremental")
    await process_one(sessionmaker_fixture, storage=storage)
    assert calls == ["agent-model"]
    async with sessionmaker_fixture() as session:
        run = await session.get(MaintenanceRun, run_id)
        assert run.incomplete_count == 1
        assert run.reasons == {"model_configuration_error": 1}


async def test_unknown_selection_refused_without_creating_policy(client, db_session):
    response = await configure_model(client, "f" * 64)
    assert response.status_code == 422
    assert await db_session.scalar(select(MaintenancePolicy)) is None


async def test_old_policies_default_and_changes_cancel_the_old_run(client, sessionmaker_fixture):
    _, selected = await models(client)
    first = await client.put(
        "/api/v1/maintenance-agent/policies/company", headers=headers(), json={}
    )
    assert first.status_code == 200
    assert first.json()["settings"]["model_ref"] == "system_default"
    run_id = await run_asset(sessionmaker_fixture)
    changed = await configure_model(client, selected["model_ref"], first.json()["revision"])
    assert changed.status_code == 200
    async with sessionmaker_fixture() as session:
        run = await session.get(MaintenanceRun, run_id)
        assert run.status == "cancelled"
        assert run.reasons["policy_changed"] == 1
