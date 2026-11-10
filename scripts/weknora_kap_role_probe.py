"""Real HTTPS KAP role flows over fresh PostgreSQL and live WeKnora fixtures.

Run only inside the isolated live probe container. No production environment is copied.
Fixture creation is setup, not evidence of KAP upload/approval-publishing acceptance.
"""

import asyncio
from contextlib import AsyncExitStack
from datetime import datetime, timedelta, timezone
import ipaddress
import json
import os
from pathlib import Path
import secrets
import signal
import ssl
import subprocess
import sys
import traceback
from urllib.parse import urlsplit
import uuid

import httpx

from weknora_rehearsal_diagnostics import classify

ROOT = Path("/evidence")
BACKEND = Path("/probe/backend")
REPORT = {
    "scope": "KAP HTTPS password sessions, three-role authorization with live indexed synthetic fixtures",
    "checks": [],
    "not_verified": [
        "browser UI",
        "KAP upload-confirm-publish workflow",
        "multimodal model",
        "PDF/OCR pipeline",
        "production configuration changes",
    ],
}


def check(name, passed, **facts):
    REPORT["checks"].append({"case": name, "passed": bool(passed), **facts})
    if not passed:
        raise RuntimeError("check failed: " + name)


def isolated_env(data, root=ROOT, backend=BACKEND):
    """Build an allowlisted environment; reject every non-fixture DB target."""
    from cryptography.fernet import Fernet

    parsed = urlsplit(data["database_url"])
    if not (
        parsed.scheme == "postgresql+asyncpg"
        and parsed.hostname == "127.0.0.1"
        and parsed.port == 5432
        and parsed.username == "wkfixture"
        and parsed.password
        and parsed.path == "/kap_role_fixture"
        and not parsed.query
        and not parsed.fragment
    ):
        raise RuntimeError("role probe requires the isolated fixture database")
    if data["weknora_base_url"] != "http://127.0.0.1:8080":
        raise RuntimeError("role probe requires the isolated WeKnora endpoint")
    env = {
        k: v
        for k, v in os.environ.items()
        if k
        in {"PATH", "SYSTEMROOT", "HTTPS_PROXY", "HTTP_PROXY", "KAP_REHEARSAL_ALIYUN_WORKSPACE_ID"}
    }
    env.update(
        PYTHONPATH=str(backend),
        PYTHONDONTWRITEBYTECODE="1",
        APP_ENV="prod",
        LOG_LEVEL="WARNING",
        DATABASE_URL=data["database_url"],
        WEKNORA_BASE_URL=data["weknora_base_url"],
        WEKNORA_API_KEY=data["weknora_api_key"],
        WEKNORA_TIMEOUT="90",
        GENERATION_MODEL_ENCRYPTION_KEY=Fernet.generate_key().decode(),
        GENERATION_MODEL_REF_SECRET=secrets.token_urlsafe(32),
        AUTH_ATTEMPT_HASH_SECRET=secrets.token_urlsafe(32),
        CSRF_TOKEN_SECRET=secrets.token_urlsafe(32),
        SESSION_COOKIE_SECURE="true",
        STORAGE_ROOT=str(root / "kap-role-storage"),
        REDIS_URL="redis://127.0.0.1:6379/5",
        CELERY_TASK_ALWAYS_EAGER="false" if data.get("kap_upload_flow") else "true",
        WECOM_NOTIFY_ENABLED="false",
        ONLYOFFICE_ENABLED="false",
        NO_PROXY="127.0.0.1,localhost",
    )
    return env


def tls_files(root):
    """Private local certificate, explicitly trusted by this probe (never verify=False)."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "KAP isolated rehearsal")])
    now = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(hours=2))
        .add_extension(
            x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )
    cert_path, key_path = root / "tls.pem", root / "tls-private.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    key_path.chmod(0o600)
    return cert_path, key_path


async def assert_empty_database():
    from sqlalchemy import text
    from app.db.session import get_engine

    engine = get_engine()
    async with engine.connect() as conn:
        tables = await conn.scalar(
            text("SELECT count(*) FROM information_schema.tables WHERE table_schema='public'")
        )
        check("kap_database_initially_empty", tables == 0)
    await engine.dispose()


async def seed(data):
    from sqlalchemy import select, func
    from app.db.session import get_sessionmaker, get_engine
    from app.models.identity import User, UserCompanyRole, Project, ProjectMember
    from app.models.knowledge import (
        KnowledgeAsset,
        KnowledgeAssetVersion,
        KnowledgeAssetSummary,
        KnowledgeAssetChunk,
    )
    from app.models.weknora import WeknoraKbMapping
    from app.models.weknora_defaults import WeknoraDefaultModels
    from app.models.generation_model import ContentGenerationModel, ContentGenerationSettings
    from app.services.generation_models import _encrypt
    from app.services.passwords import hash_password
    from app.services.permission_rules import ensure_default_rules
    from app.services.weknora_client import WeKnoraClient
    from weknora_live_probe import ready

    users = {
        role: {
            "id": uuid.uuid4(),
            "email": role + "@example.invalid",
            "password": secrets.token_urlsafe(24),
        }
        for role in ("consultant", "boss", "admin")
    }
    project_id = uuid.uuid4()
    fixtures = {}
    client = WeKnoraClient(
        base_url=data["weknora_base_url"], api_key=data["weknora_api_key"], timeout=90
    )
    async with get_sessionmaker()() as session:
        for role, user in users.items():
            entity = User(
                id=user["id"],
                name="虚构角色 " + role,
                email=user["email"],
                status="active",
                password_hash=hash_password(user["password"]),
                password_set_at=datetime.now(timezone.utc),
            )
            entity.company_roles.append(UserCompanyRole(company_role=role, status="active"))
            session.add(entity)
        session.add(Project(id=project_id, name="虚构星舟项目", status="active"))
        await session.flush()
        session.add(
            ProjectMember(
                project_id=project_id,
                user_id=users["consultant"]["id"],
                project_role="consultant",
                status="active",
            )
        )
        session.add(
            WeknoraDefaultModels(
                **{"default_" + slot + "_model_id": mid for slot, mid in data["models"].items()}
            )
        )
        generation = data["generation"]
        model = ContentGenerationModel(
            id=uuid.uuid4(),
            display_name="虚构验收生成连接",
            provider=generation["provider"],
            model_name=generation["model"],
            base_url_ciphertext=_encrypt(generation["base_url"]),
            api_key_ciphertext=_encrypt(generation["api_key"]),
            enabled=True,
            capability_type="chat",
        )
        session.add(model)
        await session.flush()
        session.add(ContentGenerationSettings(id=1, default_model_id=model.id))
        await ensure_default_rules(session)
        await session.commit()
        mappings = {}
        for label, scope, owner, level in (
            ("company", "company", "boss", "L2"),
            ("classified", "company", "boss", "L5"),
            ("personal_consultant", "personal", "consultant", "L2"),
            ("personal_boss", "personal", "boss", "L2"),
            ("project", "project", "consultant", "L2"),
        ):
            mapping_key = (scope, owner if scope == "personal" else "")
            if mapping_key not in mappings:
                kb = await client.create_kb(
                    name="虚构星舟 " + label, embedding_model_id=data["models"]["embedding"]
                )
                await client.update_initialization_config(
                    kb,
                    config={
                        "llmModelId": data["models"]["chat"],
                        "embeddingModelId": data["models"]["embedding"],
                        "documentSplitting": {
                            "chunkSize": 512,
                            "chunkOverlap": 64,
                            "separators": ["\n\n", "\n", "。"],
                        },
                        "storageProvider": "local",
                        "multimodal": {"enabled": False},
                        "vlm_config": {"enabled": False},
                        "questionGeneration": {"enabled": False, "questionCount": 3},
                        "nodeExtract": {"enabled": False},
                    },
                )
                mappings[mapping_key] = kb
                session.add(
                    WeknoraKbMapping(
                        scope=scope,
                        owner_user_id=users[owner]["id"] if scope == "personal" else None,
                        project_id=project_id if scope == "project" else None,
                        weknora_kb_id=kb,
                        embedding_model_id=data["models"]["embedding"],
                        kb_name="fixture-" + label,
                        display_name="虚构星舟资料",
                        status="active",
                    )
                )
            kb = mappings[mapping_key]
            marker = "KAPROLE" + secrets.token_hex(8).upper()
            content = (
                "# 虚构星舟检修资料\n星舟检修间隔为17天，每次由两名工程师完成。仅供验收。\n原文核对码："
                + marker
                + "。\n"
            )
            if label == "classified":
                content += "虚构客户名称：星舟示例客户有限公司。虚构联系人：张示例。\n"
            document = await client.upload_file(
                kb_id=kb, content=content.encode(), file_name=label + ".md", mime="text/markdown"
            )
            doc_id = str(document["id"])
            await ready(client, doc_id)
            check("role_fixture_live_indexed", True, fixture=label)
            aid, vid = uuid.uuid4(), uuid.uuid4()
            session.add(
                KnowledgeAsset(
                    id=aid,
                    title="虚构星舟检修 " + label,
                    scope=scope,
                    zone="asset",
                    asset_type="methodology",
                    owner_user_id=users[owner]["id"],
                    maintainer_user_id=users[owner]["id"],
                    project_id=project_id if scope == "project" else None,
                    current_version_id=vid,
                    visibility="public" if scope == "company" else "private",
                    confidentiality_level=level,
                    ai_access_level="A1",
                    asset_status="active",
                )
            )
            await session.flush()
            session.add(
                KnowledgeAssetVersion(
                    id=vid,
                    asset_id=aid,
                    version_no="V1",
                    version_status="active",
                    created_by=users[owner]["id"],
                    weknora_kb_id=kb,
                    weknora_doc_id=doc_id,
                    weknora_parse_status="completed",
                    index_status="indexed",
                    directory_key="company.methodology" if scope == "company" else None,
                )
            )
            await session.flush()
            for kind in ("one_liner", "detailed", "redacted_summary"):
                session.add(
                    KnowledgeAssetSummary(
                        asset_id=aid,
                        version_id=vid,
                        summary_type=kind,
                        content="虚构星舟检修的安全摘要，不含原文核对码。",
                    )
                )
            fixtures[label] = {"id": str(aid), "marker": marker, "kb": kb, "doc": doc_id}
        await session.commit()
        check(
            "no_local_chunk_fallback",
            await session.scalar(select(func.count()).select_from(KnowledgeAssetChunk)) == 0,
        )
    await get_engine().dispose()
    return users, fixtures


def assert_safe(body, fixtures, allowed_markers=()):
    text = json.dumps(body, ensure_ascii=False)
    forbidden = ["weknora_kb_id", "weknora_doc_id", "api_key", "storage_ref"]
    for label, fixture in fixtures.items():
        forbidden.extend([fixture["kb"], fixture["doc"]])
        if label not in allowed_markers:
            forbidden.append(fixture["marker"])
    if any(value in text for value in forbidden):
        raise RuntimeError("role response exposed forbidden fixture information")


async def exercise(users, fixtures, cert_path, process, *, upload_flow=False):
    base = "https://127.0.0.1:18443"
    verify = ssl.create_default_context(cafile=str(cert_path))
    async with AsyncExitStack() as stack:
        anonymous = await stack.enter_async_context(
            httpx.AsyncClient(base_url=base, verify=verify, trust_env=False, timeout=90)
        )
        for _ in range(80):
            if process.poll() is not None:
                raise RuntimeError("isolated KAP server exited")
            try:
                response = await anonymous.get("/api/v1/auth/me")
                if response.status_code == 401:
                    break
            except httpx.RequestError:
                pass
            await asyncio.sleep(0.5)
        else:
            raise RuntimeError("isolated KAP HTTPS startup timeout")
        check("kap_anonymous_rejected", response.status_code == 401)
        dev = await anonymous.get(
            "/api/v1/auth/me", headers={"X-Dev-User-Id": str(users["boss"]["id"])}
        )
        check("kap_production_mode_rejects_dev_header", dev.status_code == 401)
        clients = {}
        for role, user in users.items():
            http = await stack.enter_async_context(
                httpx.AsyncClient(base_url=base, verify=verify, trust_env=False, timeout=120)
            )
            response = await http.post(
                "/api/v1/auth/login", json={"email": user["email"], "password": user["password"]}
            )
            check("kap_password_login", response.status_code == 200, role=role)
            check(
                "kap_session_identity",
                response.json().get("user_id") == str(user["id"])
                and response.json().get("active_company_role") == role,
                role=role,
            )
            check(
                "kap_secure_session_cookie",
                "secure" in response.headers.get("set-cookie", "").lower()
                and bool(http.cookies.get("kap_session")),
                role=role,
            )
            csrf = await http.get("/api/v1/auth/csrf")
            check("kap_csrf_issued", csrf.status_code == 200, role=role)
            http.headers["X-CSRF-Token"] = csrf.json()["csrf_token"]
            clients[role] = http
        denied = await clients["consultant"].post(
            "/api/v1/knowledge/search",
            json={"query": "星舟检修"},
            headers={"X-CSRF-Token": "invalid"},
        )
        check("kap_invalid_csrf_rejected", denied.status_code == 403)

        # The source assets exist and are indexed before testing every denied branch.
        visible = {
            "consultant": {"company", "personal_consultant", "project"},
            "boss": {"company", "classified", "personal_boss", "project"},
            "admin": set(),
        }
        originals = {
            "consultant": {"personal_consultant", "project"},
            "boss": {"company", "classified", "personal_boss"},
            "admin": set(),
        }
        for role, http in clients.items():
            for label, fixture in fixtures.items():
                response = await http.get("/api/v1/knowledge/" + fixture["id"])
                expected = 200 if label in visible[role] else 404
                check(
                    "kap_detail_permission",
                    response.status_code == expected,
                    role=role,
                    fixture=label,
                    status=response.status_code,
                )
                assert_safe(response.json(), fixtures)
                if expected == 200:
                    check(
                        "kap_detail_original_permission",
                        response.json()["access_info"]["original"] == (label in originals[role]),
                        role=role,
                        fixture=label,
                    )
            response = await http.post(
                "/api/v1/knowledge/search",
                json={"query": "星舟检修", "scope": "all", "intent": "search"},
            )
            if role == "admin":
                check(
                    "kap_admin_search_empty",
                    response.status_code == 200 and response.json()["cards"] == [],
                )
                assert_safe(response.json(), fixtures)
                for label, fixture in fixtures.items():
                    denied = await http.post(
                        "/api/v1/knowledge/search",
                        json={
                            "query": "星舟检修",
                            "intent": "search",
                            "want_original": True,
                            "asset_id": fixture["id"],
                        },
                    )
                    check(
                        "kap_admin_original_denied",
                        denied.status_code == 200
                        and denied.json()["cards"] == []
                        and not denied.json()["original"]["available"]
                        and not denied.json()["original"]["chunks"],
                        fixture=label,
                    )
                    assert_safe(denied.json(), fixtures)
                continue
            check("kap_search_status", response.status_code == 200, role=role)
            body = response.json()
            assert_safe(body, fixtures)
            ids = {card["asset_id"] for card in body["cards"]}
            check(
                "kap_search_scope_filter",
                ids == {fixtures[label]["id"] for label in visible[role]},
                role=role,
            )
            for label, fixture in fixtures.items():
                response = await http.post(
                    "/api/v1/knowledge/search",
                    json={
                        "query": "星舟检修",
                        "intent": "search",
                        "scope": "all",
                        "want_original": True,
                        "asset_id": fixture["id"],
                    },
                )
                check("kap_original_status", response.status_code == 200, role=role, fixture=label)
                body = response.json()
                original = body["original"]
                permitted = label in originals[role]
                check(
                    "kap_original_permission",
                    original["available"] == permitted,
                    role=role,
                    fixture=label,
                )
                if permitted:
                    # L5 goes through entity desensitization; require actual chunks but not exact marker retention.
                    content = "\n".join(c["content"] for c in original["chunks"])
                    check(
                        "kap_live_original_content",
                        bool(content) and (label == "classified" or fixture["marker"] in content),
                        role=role,
                        fixture=label,
                    )
                else:
                    check(
                        "kap_denied_original_empty",
                        not original["chunks"],
                        role=role,
                        fixture=label,
                    )
                assert_safe(body, fixtures, {label} if permitted else set())

        # A real authorization request/approval/revocation cycle, not direct grant seeding.
        consultant, boss, admin = (clients[r] for r in ("consultant", "boss", "admin"))
        company = fixtures["company"]
        request = await consultant.post(
            f"/api/v1/knowledge/{company['id']}/original-access/request",
            json={"reason": "虚构验收"},
        )
        check(
            "kap_access_request_created",
            request.status_code == 200 and request.json().get("status") == "created",
        )
        request_id = request.json()["request"]["request_id"]
        approval_path = f"/api/v1/original-access/requests/{request_id}/approve"
        denied = await admin.post(approval_path, json={})
        check("kap_admin_cannot_approve_business_access", denied.status_code == 403)
        approved = await boss.post(approval_path, json={"note": "虚构验收授权"})
        check(
            "kap_governance_approves_access",
            approved.status_code == 200 and approved.json().get("status") == "approved",
        )
        grant_id = approved.json()["grant"]["grant_id"]
        search = {
            "query": "星舟检修",
            "scope": "company",
            "intent": "search",
            "want_original": True,
            "asset_id": company["id"],
        }
        granted = await consultant.post("/api/v1/knowledge/search", json=search)
        check(
            "kap_granted_original_available",
            granted.status_code == 200
            and granted.json()["original"]["available"]
            and company["marker"] in json.dumps(granted.json()["original"]),
        )
        assert_safe(granted.json(), fixtures, {"company"})
        revoked = await boss.post(
            f"/api/v1/original-access/grants/{grant_id}/revoke", json={"reason": "虚构验收撤销"}
        )
        check(
            "kap_grant_revoked",
            revoked.status_code == 200 and revoked.json().get("status") == "revoked",
        )
        denied = await consultant.post("/api/v1/knowledge/search", json=search)
        check(
            "kap_revocation_effective",
            denied.status_code == 200
            and not denied.json()["original"]["available"]
            and not denied.json()["original"]["chunks"],
        )
        assert_safe(denied.json(), fixtures)

        # Real KAP QA over the caller's own indexed document; check attribution and isolation.
        for role in ("consultant", "boss"):
            qa = await clients[role].post(
                "/api/v1/knowledge/search",
                json={"query": "星舟检修间隔是多少天？", "scope": "personal", "intent": "qa"},
            )
            check(
                "kap_grounded_qa",
                qa.status_code == 200
                and qa.json().get("answer_status") == "answered"
                and "17" in (qa.json().get("answer") or ""),
                role=role,
            )
            body = qa.json()
            own = "personal_" + role
            check(
                "kap_qa_citation_scope",
                bool(body["citations"])
                and all(c["asset_id"] == fixtures[own]["id"] for c in body["citations"]),
                role=role,
            )
            assert_safe(body, fixtures, {own})
        if upload_flow:
            from weknora_kap_upload_probe import run as run_upload

            await run_upload(clients, users, check)
            REPORT["upload_workflow_passed"] = True
            REPORT["not_verified"].remove("KAP upload-confirm-publish workflow")
            REPORT["not_verified"].extend(
                [
                    "KAP upload formats other than Markdown",
                    "company promotion workflow",
                    "production worker topology and periodic scheduling",
                ]
            )
        for role, http in clients.items():
            prior_cookie = http.cookies.get("kap_session")
            logout = await http.post("/api/v1/auth/logout")
            check("kap_logout", logout.status_code in (200, 204), role=role)
            check(
                "kap_session_invalidated",
                (await http.get("/api/v1/auth/me")).status_code == 401,
                role=role,
            )
            replay = await anonymous.get(
                "/api/v1/auth/me", headers={"Cookie": "kap_session=" + prior_cookie}
            )
            check("kap_logged_out_cookie_rejected", replay.status_code == 401, role=role)


async def audit_check(users):
    from sqlalchemy import select
    from app.db.session import get_sessionmaker, get_engine
    from app.models.audit import AuditEvent
    from app.schemas.enums import AuditAction

    async with get_sessionmaker()() as session:
        events = (await session.execute(select(AuditEvent))).scalars().all()
        for role, user in users.items():
            check(
                "kap_password_login_audited",
                any(
                    e.actor_user_id == user["id"]
                    and e.action == "login.success"
                    and (e.extra or {}).get("login_method") == "password"
                    for e in events
                ),
                role=role,
            )
        for actor, action in (
            ("consultant", AuditAction.access_original_requested.value),
            ("boss", AuditAction.access_original_approved.value),
            ("boss", AuditAction.access_original_grant_revoked.value),
        ):
            check(
                "kap_access_change_audited",
                any(e.actor_user_id == users[actor]["id"] and e.action == action for e in events),
                action=action,
            )
    await get_engine().dispose()


def main():
    os.umask(0o077)
    process = None
    worker = None
    ok = False
    runtime = ROOT / "kap-role-runtime"
    runtime.mkdir()
    with (ROOT / "kap-role-private.log").open("w") as log:
        try:
            data = json.loads((ROOT / "kap-role-private.json").read_text())
            if data.get("kap_upload_flow"):
                REPORT["scope"] += (
                    "; asynchronous Markdown intake, personal confirmation and reviewed project publication"
                )
            env = isolated_env(data)
            os.environ.clear()
            os.environ.update(env)
            os.chdir(runtime)
            sys.path.insert(0, str(BACKEND))
            asyncio.run(assert_empty_database())
            migration = "from alembic.config import Config; from alembic import command; c=Config('/probe/backend/alembic.ini'); c.set_main_option('script_location','/probe/backend/alembic'); command.upgrade(c,'head')"
            subprocess.run(
                [sys.executable, "-c", migration],
                env=env,
                stdout=log,
                stderr=log,
                timeout=180,
                check=True,
            )
            check("kap_fresh_migrations", True)
            users, fixtures = asyncio.run(seed(data))
            cert, key = tls_files(runtime)
            if data.get("kap_upload_flow"):
                worker = subprocess.Popen(
                    [
                        sys.executable,
                        "-m",
                        "celery",
                        "-A",
                        "app.worker.celery_app:celery_app",
                        "worker",
                        "--concurrency=1",
                        "--pool=prefork",
                        "-Q",
                        # Functional rehearsal only; capacity tests use separate workers.
                        "default,ocr,parse",
                        "--hostname=kap-rehearsal@fixture",
                        "--without-gossip",
                        "--without-mingle",
                        "--without-heartbeat",
                        "--loglevel=WARNING",
                    ],
                    env=env,
                    stdout=log,
                    stderr=log,
                    start_new_session=True,
                )
                from app.worker.celery_app import celery_app

                worker_ready = False
                for _ in range(30):
                    if worker.poll() is not None:
                        break
                    if celery_app.control.ping(destination=["kap-rehearsal@fixture"], timeout=1):
                        worker_ready = True
                        break
                check("kap_async_worker_ready", worker_ready)
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "app.main:app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    "18443",
                    "--ssl-certfile",
                    str(cert),
                    "--ssl-keyfile",
                    str(key),
                    "--no-access-log",
                ],
                env=env,
                stdout=log,
                stderr=log,
            )
            asyncio.run(
                exercise(
                    users, fixtures, cert, process, upload_flow=data.get("kap_upload_flow", False)
                )
            )
            asyncio.run(audit_check(users))
            ok = True
        except Exception:
            failure = traceback.format_exc()
            log.write(failure)
            REPORT["failure"] = classify(failure)
        finally:
            if worker is not None:
                try:
                    worker.terminate()
                except ProcessLookupError:
                    pass
                try:
                    worker.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    os.killpg(worker.pid, signal.SIGKILL)
                    worker.wait(timeout=10)
            if process is not None:
                process.terminate()
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)
            REPORT["passed"] = ok
            (ROOT / "kap-role-report.json").write_text(
                json.dumps(REPORT, ensure_ascii=False, indent=2)
            )
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
