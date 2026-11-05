"""Live KAP onboarding over fresh isolated PostgreSQL and WeKnora; no production writes."""

import asyncio
import json
import os
from pathlib import Path
import re
import secrets
import socket
import ssl
import subprocess
import sys
import traceback
import uuid

import httpx

import weknora_kap_role_probe as role
import weknora_live_probe as live
from weknora_live_egress import WORKSPACE_ENV, validate_model_hosts, workspace_host
from weknora_rehearsal_diagnostics import classify

ROOT = Path("/evidence")
BASE = "/api/v1/admin/model-registry"
REPORT = {
    "scope": "live KAP shared-connection onboarding, Aliyun embedding/rerank and DeepSeek chat",
    "checks": [],
    "not_verified": [
        "browser live-model submission",
        "file lifecycle",
        "role matrix",
        "PDF/OCR",
        "production changes",
    ],
}


def check(name, passed, **facts):
    REPORT["checks"].append({"case": name, "passed": bool(passed), **facts})
    if not passed:
        raise RuntimeError("check failed: " + name)


def selected_models(data, workspace):
    host = workspace_host(workspace)
    result = {}
    for slot in ("embedding", "rerank", "chat"):
        model = data["models"][slot]
        params = model.get("parameters") or {}
        if isinstance(params, str):
            params = json.loads(params)
        params = live.decrypt(params, data["aes_key"].encode())
        url = params.get("base_url", "").rstrip("/")
        expected = {
            "embedding": {"https://" + host + "/compatible-mode/v1"},
            "rerank": {"https://" + host + "/api/v1/services/rerank/text-rerank/text-rerank"},
            "chat": {"https://api.deepseek.com", "https://api.deepseek.com/v1"},
        }[slot]
        check("selected_endpoint_allowed", url in expected, usage=slot)
        check("selected_key_present", bool(params.get("api_key")), usage=slot)
        check("custom_authorization_absent", not params.get("custom_headers"), usage=slot)
        result[slot] = {"name": model["name"], "key": params["api_key"], "url": url}
    check("aliyun_same_api_key", result["embedding"]["key"] == result["rerank"]["key"])
    return result


async def network_and_tenant():
    expected_hosts = validate_model_hosts(json.loads((ROOT / "model-hosts.json").read_text()))
    for host, expected in expected_hosts.items():
        actual = {row[4][0] for row in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)}
        check("model_host_resolution", bool(actual) and actual == set(expected), host=host)
    async with httpx.AsyncClient(timeout=5, trust_env=False) as http:
        blocked = False
        try:
            await http.get("https://api.deepseek.com")
        except httpx.RequestError:
            blocked = True
        check("direct_external_access_blocked", blocked)
    async with httpx.AsyncClient(
        proxy=os.environ["HTTPS_PROXY"], timeout=5, trust_env=False
    ) as http:
        denied = False
        try:
            await http.get("https://example.com")
        except httpx.ProxyError as exc:
            denied = "403" in str(exc)
        check("unapproved_egress_denied", denied)
    async with httpx.AsyncClient(
        base_url="http://127.0.0.1:8080", timeout=30, trust_env=False
    ) as http:
        name = "registry-fixture-" + secrets.token_hex(4)
        credentials = {
            "username": name,
            "email": name + "@example.invalid",
            "password": secrets.token_urlsafe(20) + "A1!",
        }
        response = await http.post("/api/v1/auth/register", json=credentials)
        check("synthetic_weknora_account", response.status_code == 201)
        response = await http.post(
            "/api/v1/auth/login", json={k: credentials[k] for k in ("email", "password")}
        )
        check("synthetic_weknora_login", response.status_code == 200)
        login = response.json()
        http.headers["Authorization"] = "Bearer " + login["token"]
        response = await http.post(
            f"/api/v1/tenants/{login['active_tenant']['id']}/api-keys",
            json={"name": "registry-fixture", "full_access": True},
        )
        check("synthetic_weknora_api_key", response.status_code == 201)
        return response.json()["data"]["token"]


async def seed_admin():
    from app.db.session import get_sessionmaker, get_engine
    from app.db.utils import utc_now
    from app.models.identity import User, UserCompanyRole
    from app.services.passwords import hash_password
    from app.services.permission_rules import ensure_default_rules

    user = {
        "id": uuid.uuid4(),
        "email": "registry-admin@example.invalid",
        "password": secrets.token_urlsafe(24),
    }
    async with get_sessionmaker()() as session:
        entity = User(
            id=user["id"],
            name="虚构模型验收管理员",
            email=user["email"],
            status="active",
            password_hash=hash_password(user["password"]),
            password_set_at=utc_now(),
        )
        entity.company_roles.append(UserCompanyRole(company_role="admin", status="active"))
        session.add(entity)
        await ensure_default_rules(session)
        await session.commit()
    await get_engine().dispose()
    return user


async def exercise(user, models, workspace, cert, process):
    async with httpx.AsyncClient(
        base_url="https://127.0.0.1:18443",
        verify=ssl.create_default_context(cafile=str(cert)),
        trust_env=False,
        timeout=180,
    ) as http:
        for _ in range(80):
            if process.poll() is not None:
                raise RuntimeError("isolated KAP exited")
            try:
                response = await http.get("/api/v1/auth/me")
                if response.status_code == 401:
                    break
            except httpx.RequestError:
                pass
            await asyncio.sleep(0.5)
        else:
            raise RuntimeError("isolated KAP startup timeout")
        check("kap_anonymous_rejected", response.status_code == 401)
        response = await http.post(
            "/api/v1/auth/login", json={k: user[k] for k in ("email", "password")}
        )
        check("kap_password_login", response.status_code == 200)
        check(
            "kap_secure_session",
            bool(http.cookies.get("kap_session"))
            and "secure" in response.headers.get("set-cookie", "").lower(),
        )
        response = await http.get("/api/v1/auth/csrf")
        check("kap_csrf_issued", response.status_code == 200)
        http.headers["X-CSRF-Token"] = response.json()["csrf_token"]

        async def request(method, path, body=None, expected=200):
            response = await http.request(method, path, json=body)
            check(
                "registry_api_response",
                response.status_code == expected,
                method=method,
                operation=path.rsplit("/", 1)[-1]
                if path.endswith(("verify", "sync"))
                else "configuration",
                status=response.status_code,
            )
            check(
                "api_keys_not_returned", all(m["key"] not in response.text for m in models.values())
            )
            return response.json()

        initial = await request("GET", BASE)
        check("registry_initially_empty", initial == {"connections": [], "models": []})
        defaults_before = await request("GET", "/api/v1/admin/model-connections/usages/current")
        wk_defaults_before = await request("GET", "/api/v1/admin/weknora/default-models")
        aliyun = await request(
            "POST",
            BASE + "/connections",
            {
                "request_id": str(uuid.uuid4()),
                "name": "虚构验收 · 阿里云共享连接",
                "provider": "aliyun",
                "region": "cn-beijing",
                "workspace_id": workspace,
                "api_key": models["embedding"]["key"],
            },
            201,
        )
        deepseek = await request(
            "POST",
            BASE + "/connections",
            {
                "request_id": str(uuid.uuid4()),
                "name": "虚构验收 · DeepSeek",
                "provider": "deepseek",
                "api_key": models["chat"]["key"],
                "endpoints": {"chat": {"url": models["chat"]["url"], "protocol": "openai"}},
            },
            201,
        )
        ready = {}
        for slot in ("embedding", "rerank", "chat"):
            connection = deepseek if slot == "chat" else aliyun
            payload = {
                "request_id": str(uuid.uuid4()),
                "connection_id": connection["id"],
                "display_name": "虚构验收 · " + slot,
                "model_name": models[slot]["name"],
                "capability": slot,
                "dimension": 1024 if slot == "embedding" else None,
                "usages": ["business", "knowledge"] if slot == "chat" else ["knowledge"],
            }
            draft = await request("POST", BASE + "/models", payload, 201)
            replay = await request("POST", BASE + "/models", payload, 201)
            check("draft_idempotent", replay["id"] == draft["id"], usage=slot)
            check(
                "draft_not_provisioned",
                not draft["external_ref"] and not draft["knowledge_ref"],
                usage=slot,
            )
            url = BASE + "/models/" + draft["id"]
            verified = await request("POST", url + "/verify", {"signature": draft["signature"]})
            check(
                "live_registry_capability",
                verified["test_status"] == "verified",
                usage=slot,
                code=verified["test_code"],
            )
            if slot == "embedding":
                check("live_embedding_1024", verified["observed_dimension"] == 1024)
            synced = await request("POST", url + "/sync", {"signature": verified["signature"]})
            for usage in synced["usages"]:
                check(
                    "runtime_binding_verified",
                    synced["bindings"][usage]["current"],
                    model=slot,
                    usage=usage,
                    code=synced["bindings"][usage]["error_code"],
                )
            replay = await request("POST", url + "/sync", {"signature": synced["signature"]})
            check(
                "runtime_binding_idempotent",
                all(replay[k] == synced[k] for k in ("external_ref", "knowledge_ref")),
                usage=slot,
            )
            ready[slot] = synced
        inventory = await request("GET", BASE)
        check(
            "three_models_two_connections",
            len(inventory["models"]) == 3 and len(inventory["connections"]) == 2,
        )
        shared = next(c for c in inventory["connections"] if c["id"] == aliyun["id"])
        check(
            "embedding_rerank_share_connection",
            shared["model_count"] == 2
            and ready["embedding"]["connection_id"] == ready["rerank"]["connection_id"],
        )
        knowledge_options = await request("GET", "/api/v1/admin/weknora/models")
        check(
            "three_knowledge_models_selectable_without_duplicates",
            len(knowledge_options["items"]) == 3
            and {item["model_ref"] for item in knowledge_options["items"]}
            == {model["knowledge_ref"] for model in ready.values()},
        )
        external = await request(
            "POST",
            "/api/v1/admin/model-connections/items/" + ready["chat"]["external_ref"] + "/test",
            {},
        )
        check("live_deepseek_business_runtime", external.get("success") is True)
        check(
            "business_default_unchanged",
            defaults_before
            == await request("GET", "/api/v1/admin/model-connections/usages/current"),
        )
        check(
            "knowledge_defaults_unchanged",
            wk_defaults_before == await request("GET", "/api/v1/admin/weknora/default-models"),
        )


def main():
    os.umask(0o077)
    process = None
    ok = False
    runtime = ROOT / "kap-registry-runtime"
    runtime.mkdir()
    with (ROOT / "kap-registry-private.log").open("w") as log:
        try:
            data = json.loads((ROOT / "live-private.json").read_text())
            check("explicit_registry_mode", data.get("kap_model_registry") is True)
            proxy = os.environ.get("HTTPS_PROXY", "")
            check(
                "isolated_gateway_address",
                bool(re.fullmatch(r"http://wk-live-[a-f0-9]{10}-egress:18080", proxy)),
            )
            workspace = os.environ[WORKSPACE_ENV]
            # No credential-bearing request occurs until egress denial checks pass.
            api_key = asyncio.run(network_and_tenant())
            models = selected_models(data, workspace)
            env = role.isolated_env(
                {
                    "database_url": data["kap_database_url"],
                    "weknora_base_url": "http://127.0.0.1:8080",
                    "weknora_api_key": api_key,
                }
            )
            env["MODEL_REGISTRY_PROXY_URL"] = proxy
            os.environ.clear()
            os.environ.update(env)
            os.chdir(runtime)
            sys.path.insert(0, "/probe/backend")
            role.REPORT = REPORT
            asyncio.run(role.assert_empty_database())
            migration = "from alembic.config import Config; from alembic import command; c=Config('/probe/backend/alembic.ini'); c.set_main_option('script_location','/probe/backend/alembic'); command.upgrade(c,'head')"
            subprocess.run(
                [sys.executable, "-c", migration], stdout=log, stderr=log, check=True, timeout=180
            )
            check("fresh_kap_migrations", True)
            user = asyncio.run(seed_admin())
            cert, key = role.tls_files(runtime)
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
            asyncio.run(exercise(user, models, workspace, cert, process))
            ok = True
        except Exception:
            failure = traceback.format_exc()
            log.write(failure)
            REPORT["failure"] = classify(failure)
        finally:
            if process:
                process.terminate()
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)
            REPORT["passed"] = ok
            (ROOT / "live-report.json").write_text(json.dumps(REPORT, ensure_ascii=False, indent=2))
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
