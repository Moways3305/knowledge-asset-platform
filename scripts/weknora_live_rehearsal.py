"""Fresh synthetic database with a two-domain egress gateway; never switches production."""

import argparse
import copy
import hashlib
import http.client
import json
import os
from pathlib import Path
import secrets
import signal
import ssl
import subprocess
import time
import traceback
import uuid

import weknora_app_rehearsal as app
import weknora_live_egress as egress
import weknora_pg_upgrade_rehearsal as pg


GATEWAY_CHECK = """import http.client, sys
connection = http.client.HTTPConnection(sys.argv[1], int(sys.argv[2]), timeout=2)
try:
    connection.request('CONNECT', 'forbidden.invalid:443')
    response = connection.getresponse()
    if response.status != 403:
        raise SystemExit(1)
finally:
    connection.close()
"""


def workspace_env_args(workspace_id):
    egress.allowed_hosts(workspace_id)  # Validate before passing it to Docker.
    return ["-e", egress.WORKSPACE_ENV + "=" + workspace_id]


def print_report_if_readable(stage):
    """A report I/O failure must not mask the original error or interrupt cleanup."""
    try:
        report = json.loads((stage / "live-report.json").read_text())
    except FileNotFoundError:
        return False
    except (OSError, ValueError):
        print("脱敏报告暂不可读取；保留原记录，容器收尾继续执行。", flush=True)
        return False
    print(json.dumps(report, ensure_ascii=False), flush=True)
    return True


def gateway_runtime_args(image, source, workspace_id=""):
    # git archive under umask 077 is unreadable by the image's non-root user.
    # This standalone, public script needs neither a host mount nor credentials.
    return [
        "--read-only",
        *workspace_env_args(workspace_id),
        "--entrypoint",
        "python",
        image,
        "-u",
        "-c",
        source,
    ]


def wait_gateway(name):
    for _ in range(20):
        state = pg.inspect(name)["State"]
        pg.require(state.get("Running") is True, "egress gateway exited before readiness")
        result = subprocess.run(
            ["docker", "exec", name, "python", "-c", GATEWAY_CHECK, "127.0.0.1", "18080"],
            stdout=pg.PRIVATE,
            stderr=pg.PRIVATE,
            timeout=5,
        )
        if result.returncode == 0:
            return
        time.sleep(0.5)
    raise RuntimeError("egress gateway readiness timeout")


def model_host_args(mapping, allowed=None):
    result = []
    for host, addresses in sorted(egress.validate_model_hosts(mapping, allowed).items()):
        for address in addresses:
            result.extend(["--add-host", host + ":" + address])
    return result


def assert_shared_hosts(child, parent):
    pg.require(
        parent.get("HostsPath") and child.get("HostsPath") == parent["HostsPath"],
        "isolated child does not share model hosts mapping",
    )


def assert_network(item, expected, run, ui_port=None):
    pg.require(
        item["Config"].get("Labels", {}).get(pg.LABEL) == str(run), "resource label mismatch"
    )
    bindings = item["HostConfig"].get("PortBindings") or {}
    wanted = {"18443/tcp": [{"HostIp": "127.0.0.1", "HostPort": str(ui_port)}]} if ui_port else {}
    pg.require(bindings == wanted, "unexpected published ports")
    pg.require(not item["HostConfig"].get("Privileged"), "privileged container forbidden")
    pg.require(
        set(item["NetworkSettings"]["Networks"]) == set(expected), "network attachment changed"
    )


def build_ui(repo, stage, token, run):
    """Build only public frontend sources, before mounting any fixture credentials."""
    image = "kap-isolated-ui-build:" + token
    name = "kap-isolated-ui-build-" + token
    print("构建本轮隔离前端；构建日志保留在 private.log。", flush=True)
    pg.docker(
        "build",
        "--target",
        "build",
        "-f",
        str(repo / "Dockerfile.frontend"),
        "-t",
        image,
        str(repo),
    )
    pg.docker(
        "create", "--name", name, "--network", "none", "--label", pg.LABEL + "=" + str(run), image
    )
    try:
        pg.docker("cp", name + ":/app/dist", str(stage / "ui-dist"))
    finally:
        pg.docker("rm", name)
    pg.require((stage / "ui-dist/index.html").is_file(), "frontend build missing")


def wait_ui_session(
    tester, database, gateway, relay, internal, outside, stage, run, before, port, minutes
):
    pg.docker("start", tester)
    deadline = time.monotonic() + (minutes + 10) * 60
    announced = False
    while pg.inspect(tester)["State"]["Running"]:
        pg.require(time.monotonic() < deadline, "UI session timeout")
        if not announced:
            try:
                ready = json.loads((stage / "ui-ready.json").read_text())
            except (FileNotFoundError, PermissionError):
                ready = None
            if ready:
                pg.require(ready.get("ready") is True, "UI not ready")
                assert_network(pg.inspect(database), [internal], run)
                assert_network(pg.inspect(gateway), [internal, outside], run)
                assert_network(pg.inspect(relay), [internal, outside], run, ui_port=port)
                cert = pg.docker("exec", tester, "cat", "/evidence/kap-registry-runtime/tls.pem")
                connection = http.client.HTTPSConnection(
                    "127.0.0.1", port, context=ssl.create_default_context(cadata=cert), timeout=15
                )
                try:
                    connection.request("GET", "/login")
                    response = connection.getresponse()
                    pg.require(
                        response.status == 200 and b'<div id="root"' in response.read(),
                        "UI published HTTPS route unavailable",
                    )
                finally:
                    connection.close()
                pg.compare(before, app.production_fingerprint())
                print(json.dumps(ready, ensure_ascii=False), flush=True)
                print(
                    "虚构登录信息（仅本地查看，不回传）：" + str(stage / "ui-login-private.json"),
                    flush=True,
                )
                print("提前结束命令：touch " + str(stage / "ui-stop"), flush=True)
                print("UI 尚未验收；到期自动停止本轮测试容器。", flush=True)
                print("UI_READY：仅监听服务器 127.0.0.1；请通过 SSH 隧道访问。", flush=True)
                announced = True
        time.sleep(2)
    pg.require(announced, "UI preparation failed before readiness")
    pg.require(pg.inspect(tester)["State"]["ExitCode"] == 0, "UI session failed")


def prepare_fixture_models(
    model_rows, *, correct_rerank_endpoint=False, workspace_id="", rerank_use_embedding_key=False
):
    """Explicit, narrow correction in synthetic records only; never mutate the snapshot."""
    models = copy.deepcopy(model_rows)
    adjustments = []
    pg.require(not (correct_rerank_endpoint and workspace_id), "choose one fixture adjustment mode")
    pg.require(
        not rerank_use_embedding_key or bool(workspace_id),
        "fixture rerank key reuse requires an explicit Aliyun workspace",
    )
    if workspace_id:
        host = egress.workspace_host(workspace_id)
        old_root = "https://dashscope.aliyuncs.com"
        for slot, name, kind, path in (
            ("embedding", "text-embedding-v3", "Embedding", "/compatible-mode/v1"),
            ("rerank", "qwen3-rerank", "Rerank", "/api/v1/services/rerank/text-rerank/text-rerank"),
        ):
            model = models[slot]
            params = model.get("parameters") or {}
            if isinstance(params, str):
                params = json.loads(params)
            accepted = {old_root + "/compatible-mode/v1"}
            if slot == "rerank":
                accepted.add(old_root + path)
            pg.require(
                model.get("name") == name
                and model.get("type") == kind
                and model.get("source") == "remote"
                and params.get("provider") in (None, "", "aliyun")
                and params.get("base_url") in accepted | {url + "/" for url in accepted}
                and not params.get("spec")
                and not params.get("extra_config"),
                "workspace migration requires the diagnosed Aliyun model configuration",
            )
            params["base_url"] = "https://" + host + path
            # The upstream URL-based provider detector recognizes the old host
            # only. Pin Aliyun explicitly to keep the native rerank protocol.
            params["provider"] = "aliyun"
            model["parameters"] = params
            adjustments.append(
                {
                    "usage": slot,
                    "scope": "synthetic_model_only",
                    "from": "legacy_dashscope_endpoint",
                    "to": "beijing_workspace_endpoint",
                    "host": host,
                    "production_configuration_changed": False,
                    "credentials_changed": False,
                }
            )
        if rerank_use_embedding_key:
            embedding_params = models["embedding"]["parameters"]
            rerank_params = models["rerank"]["parameters"]
            key = embedding_params.get("api_key")
            pg.require(
                isinstance(key, str) and bool(key.strip()),
                "fixture rerank key reuse requires a stored embedding API key",
            )
            for params in (embedding_params, rerank_params):
                headers = params.get("custom_headers") or {}
                pg.require(
                    isinstance(headers, dict)
                    and not any(str(name).lower() == "authorization" for name in headers),
                    "fixture rerank key reuse does not allow custom authorization headers",
                )
            # Keep the stored ciphertext; the probe decrypts both with the same snapshot key.
            rerank_params["api_key"] = key
            for adjustment in adjustments:
                if adjustment["usage"] == "rerank":
                    adjustment.update(credentials_changed=True, credential_source="embedding")
    if correct_rerank_endpoint:
        model = models["rerank"]
        params = model.get("parameters") or {}
        if isinstance(params, str):
            params = json.loads(params)
        pg.require(
            model.get("name") == "qwen3-rerank"
            and model.get("type") == "Rerank"
            and model.get("source") == "remote"
            and params.get("provider") == "aliyun"
            and params.get("base_url")
            in (
                "https://dashscope.aliyuncs.com/compatible-mode/v1",
                "https://dashscope.aliyuncs.com/compatible-mode/v1/",
            )
            and not params.get("spec")
            and not params.get("extra_config"),
            "rerank correction requires the exact diagnosed Aliyun configuration",
        )
        params["base_url"] = (
            "https://dashscope.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank"
        )
        model["parameters"] = params
        adjustments.append(
            {
                "usage": "rerank",
                "scope": "synthetic_model_only",
                "from": "chat_embedding_base",
                "to": "dashscope_native_rerank",
                "production_configuration_changed": False,
            }
        )
    return models, adjustments


def main():
    import fcntl

    parser = argparse.ArgumentParser(description=__doc__)
    source_choice = parser.add_mutually_exclusive_group(required=True)
    source_choice.add_argument("--offline-stage", type=Path)
    source_choice.add_argument("--build-stage", type=Path)
    adjustment_choice = parser.add_mutually_exclusive_group()
    adjustment_choice.add_argument(
        "--correct-fixture-rerank-endpoint",
        action="store_true",
        help="Correct only the diagnosed Aliyun URL in the new synthetic model; report the deviation",
    )
    adjustment_choice.add_argument(
        "--aliyun-workspace-id",
        default="",
        help="Use this Beijing workspace for synthetic embedding/rerank models and exact egress allowlist",
    )
    parser.add_argument(
        "--fixture-rerank-use-embedding-key",
        action="store_true",
        help="Use the stored embedding API key for synthetic rerank only; requires --aliyun-workspace-id",
    )
    parser.add_argument(
        "--kap-role-flows",
        action="store_true",
        help="Also run real KAP HTTPS role authorization in a separate fresh fixture database",
    )
    parser.add_argument(
        "--kap-upload-flow",
        action="store_true",
        help="Extend --kap-role-flows with asynchronous Markdown upload and reviewed project publication",
    )
    parser.add_argument(
        "--kap-model-registry",
        action="store_true",
        help="Verify new KAP shared connections with live models only, without repeating file/role flows",
    )
    parser.add_argument(
        "--kap-model-ui",
        action="store_true",
        help="Prepare a loopback-only browser session; requires --kap-model-registry",
    )
    parser.add_argument("--ui-port", type=int, default=18443)
    parser.add_argument("--ui-minutes", type=int, default=90)
    args = parser.parse_args()
    if args.kap_model_ui and (
        not args.kap_model_registry
        or not 1024 <= args.ui_port <= 65535
        or not 1 <= args.ui_minutes <= 90
    ):
        parser.error("UI requires --kap-model-registry, an unprivileged port and 1–90 minutes")
    if args.kap_model_registry and (
        args.kap_role_flows
        or args.kap_upload_flow
        or not args.aliyun_workspace_id
        or not args.fixture_rerank_use_embedding_key
    ):
        parser.error(
            "--kap-model-registry requires workspace/shared embedding key and excludes role/upload flows"
        )
    if args.kap_upload_flow and not args.kap_role_flows:
        parser.error("--kap-upload-flow requires --kap-role-flows")
    if args.fixture_rerank_use_embedding_key and not args.aliyun_workspace_id:
        parser.error("--fixture-rerank-use-embedding-key requires --aliyun-workspace-id")
    allowed = egress.allowed_hosts(args.aliyun_workspace_id)
    os.umask(0o077)
    if args.build_stage:
        from weknora_keyword_app_rehearsal import passed_offline_for_build

        requested_build = args.build_stage.resolve(strict=True)
        source = passed_offline_for_build(requested_build.parent, requested_build)
    else:
        source = args.offline_stage.resolve(strict=True)
    run = source.parent
    pg.require(
        run.parent == Path("/data/weknora/upgrade-rehearsals")
        and run.name.startswith("run-")
        and run.name[4:].isalnum()
        and source.name.startswith("app090-"),
        "unexpected source directory",
    )
    pg.require(
        (source / "PASS-OFFLINE").is_file() and (source / "exit-code").read_text().strip() == "0",
        "offline rehearsal not passed",
    )
    repo = Path(__file__).resolve().parents[1]
    images = json.loads((source / "images.json").read_text())
    build_stage = Path(images["patched_build_stage"]).resolve(strict=True)
    lock = (Path.home() / ".weknora-rehearsal.lock").open("a")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    token = uuid.uuid4().hex[:10]
    stage = run / ("live090-" + token)
    stage.mkdir()
    pg.RUN, pg.STAGE = run, stage
    pg.PRIVATE = (stage / "private.log").open("ab")
    internal, outside = "wk-live-in-" + token, "wk-live-out-" + token
    database, redis, application = (
        "wk-live-" + token + suffix for suffix in ("-db", "-redis", "-app")
    )
    gateway, tester = "wk-live-" + token + "-egress", "wk-live-" + token + "-probe"
    relay = "wk-live-" + token + "-ui"
    created = []
    before, code = None, 1

    def interrupted(signum, frame):
        raise RuntimeError("rehearsal interrupted; stopping isolated containers")

    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    try:
        print("联网演练目录：" + str(stage), flush=True)
        before = app.production_fingerprint()
        pg.require(
            app.patched_image(build_stage, run, images["app_original"]) == images["app"],
            "offline image changed",
        )
        manifest = json.loads((build_stage / "build-manifest.json").read_text())
        pg.require(
            manifest.get("model_proxy_patch_sha256")
            == hashlib.sha256(
                (repo / "patches/weknora-v0.9.0-model-proxy.patch").read_bytes()
            ).hexdigest(),
            "live rehearsal requires the verified model proxy build and a new offline pass",
        )
        if args.kap_model_ui:
            build_ui(repo, stage, token, run)
        print("=== 1/4 只读取得当前模型选择，准备全新空库 ===", flush=True)
        kap = pg.inspect("kap-backend-1")
        selection = subprocess.run(
            ["docker", "exec", "-i", "kap-backend-1", "python", "-"],
            input=(repo / "scripts/weknora_live_selection.py").read_bytes(),
            stdout=subprocess.PIPE,
            stderr=pg.PRIVATE,
            timeout=60,
        )
        pg.require(selection.returncode == 0, "read-only model selection failed")
        picked = json.loads(selection.stdout)
        snapshot = json.loads((source / "probe-private.json").read_text())
        rows = {
            str(row["id"]): row
            for row in snapshot["stored_records"]["models"]
            if not row.get("deleted_at")
        }
        model_rows = {}
        for slot in ("embedding", "chat", "rerank"):
            model_id = picked["selected"].get(slot)
            pg.require(
                model_id and str(model_id) in rows, "selected model missing from verified snapshot"
            )
            model_rows[slot] = rows[str(model_id)]
            saved = model_rows[slot]
            parameters = saved.get("parameters") or {}
            if isinstance(parameters, str):
                parameters = json.loads(parameters)
            metadata = {key: saved[key] for key in ("name", "type", "source")}
            metadata["base_url"] = parameters.get("base_url", "")
            pg.require(
                metadata == picked["metadata"][slot],
                "selected model metadata changed since offline validation",
            )
        model_rows, adjustments = prepare_fixture_models(
            model_rows,
            correct_rerank_endpoint=args.correct_fixture_rerank_endpoint,
            workspace_id=args.aliyun_workspace_id,
            rerank_use_embedding_key=args.fixture_rerank_use_embedding_key,
        )
        if adjustments:
            print("仅调整本轮虚构模型配置；生产配置未修改，须后续单独验收。", flush=True)
        if args.fixture_rerank_use_embedding_key:
            print("本轮虚构重排模型使用嵌入模型的 API Key；生产密钥配置未修改。", flush=True)
        password = secrets.token_urlsafe(32)
        (stage / "live-private.json").write_text(
            json.dumps(
                {
                    "models": model_rows,
                    "aes_key": snapshot["aes_key"],
                    "generation": picked["generation"],
                    "configuration_adjustments": adjustments,
                    "kap_role_flows": args.kap_role_flows,
                    "kap_upload_flow": args.kap_upload_flow,
                    "kap_model_registry": args.kap_model_registry,
                    "kap_model_ui": args.kap_model_ui,
                    "ui_port": args.ui_port,
                    "ui_minutes": args.ui_minutes,
                    "kap_database_url": (
                        "postgresql+asyncpg://wkfixture:"
                        + password
                        + "@127.0.0.1:5432/kap_role_fixture"
                        if args.kap_role_flows or args.kap_model_registry
                        else None
                    ),
                }
            )
        )
        pg.OWNER = "wkfixture"
        app.write_env(
            stage / "db-private.env",
            {"POSTGRES_DB": "WeKnora", "POSTGRES_USER": pg.OWNER, "POSTGRES_PASSWORD": password},
        )
        settings = app.isolated_app_env(
            {"SYSTEM_AES_KEY": snapshot["aes_key"], "DB_USER": pg.OWNER, "DB_PASSWORD": password}
        )
        proxy = "http://" + gateway + ":18080"
        settings.update(
            {
                "AUTO_MIGRATE": "true",
                "DISABLE_REGISTRATION": "false",
                "HTTPS_PROXY": proxy,
                "HTTP_PROXY": proxy,
                "NO_PROXY": "127.0.0.1,localhost",
                "WEKNORA_LLM_CHAT_TIMEOUT_SECONDS": "90",
            }
        )
        app.write_env(stage / "app-private.env", settings)
        for name, is_internal in ((internal, True), (outside, False)):
            command = ["network", "create", "--label", pg.LABEL + "=" + str(run)]
            if is_internal:
                command.append("--internal")
            pg.docker(*command, name)
        network = json.loads(pg.docker("network", "inspect", internal))[0]
        pg.require(network["Internal"] is True, "internal network isolation missing")
        data_volume, file_volume = database + "-data", database + "-files"
        for volume in (data_volume, file_volume):
            pg.docker("volume", "create", "--label", pg.LABEL + "=" + str(run), volume)
        (stage / "resources.json").write_text(
            json.dumps(
                {
                    "database": database,
                    "app": application,
                    "redis": redis,
                    "gateway": gateway,
                    "tester": tester,
                    "ui_relay": relay if args.kap_model_ui else None,
                    "networks": [internal, outside],
                    "volumes": [data_volume, file_volume],
                    "fresh_database": True,
                },
                indent=2,
            )
        )

        def create(name, *args):
            pg.docker(
                "create",
                "--name",
                name,
                "--label",
                pg.LABEL + "=" + str(run),
                "--restart",
                "no",
                *args,
            )
            created.append(name)

        create(
            gateway,
            "--network",
            internal,
            "--memory",
            "256m",
            "--cpus",
            "1",
            *gateway_runtime_args(
                kap["Image"],
                (repo / "scripts/weknora_live_egress.py").read_text(),
                args.aliyun_workspace_id,
            ),
        )
        pg.docker("network", "connect", outside, gateway)
        pg.docker("start", gateway)
        assert_network(pg.inspect(gateway), [internal, outside], run)
        print("检查隔离网关启动及非白名单拦截。", flush=True)
        wait_gateway(gateway)
        print("隔离网关已就绪。", flush=True)
        resolved = subprocess.run(
            [
                "docker",
                "exec",
                gateway,
                "python",
                "-c",
                (repo / "scripts/weknora_live_egress.py").read_text(),
                "--resolve-model-hosts",
            ],
            stdout=subprocess.PIPE,
            stderr=pg.PRIVATE,
            timeout=30,
            check=True,
        )
        model_hosts = egress.validate_model_hosts(json.loads(resolved.stdout), allowed)
        (stage / "model-hosts.json").write_text(json.dumps(model_hosts))
        print("两家模型域名的公网地址已校验，仅供本轮隔离容器解析。", flush=True)
        create(
            database,
            "--network",
            internal,
            "--memory",
            "4g",
            "--cpus",
            "2",
            "--shm-size",
            "512m",
            "--env-file",
            str(stage / "db-private.env"),
            *model_host_args(model_hosts, allowed),
            "--mount",
            f"type=volume,src={data_volume},dst=/var/lib/postgresql/data",
            images["database"],
        )
        pg.docker("start", database)
        assert_network(pg.inspect(database), [internal], run)
        pg.wait(database, db="WeKnora")
        # Fresh volumes: no pg restore, production files, old Redis tasks or user records.
        pg.require(
            pg.sql(
                database,
                "SELECT count(*) FROM information_schema.tables WHERE table_schema='public' AND table_name='knowledges';",
            )
            == "0",
            "database was not empty",
        )
        if args.kap_role_flows or args.kap_model_registry:
            # ParadeDB's default template includes PostGIS/statistics relations in
            # public. KAP needs a pristine schema, just as in its PostgreSQL tests.
            # Keep assert_empty_database strict instead of ignoring inherited tables.
            pg.sql(database, "CREATE DATABASE kap_role_fixture TEMPLATE template0;")
            print("本轮另建空白 KAP 测试库，使用真实密码会话进行隔离验收。", flush=True)
        parent_id = pg.inspect(database)["Id"]
        create(
            redis,
            "--network",
            "container:" + database,
            "--memory",
            "256m",
            images["redis"],
            "redis-server",
            "--bind",
            "127.0.0.1",
            "--save",
            "",
            "--appendonly",
            "no",
        )
        pg.docker("start", redis)
        app.guard_child(redis, database, parent_id, run)
        print("=== 2/4 启动补丁镜像，仅经网关访问阿里云与 DeepSeek ===", flush=True)
        create(
            application,
            "--network",
            "container:" + database,
            "--memory",
            "4g",
            "--cpus",
            "2",
            "--env-file",
            str(stage / "app-private.env"),
            "--mount",
            f"type=volume,src={file_volume},dst=/data/files",
            images["app"],
        )
        pg.docker("start", application)
        assert_shared_hosts(pg.inspect(application), pg.inspect(database))
        for _ in range(120):
            state = app.guard_child(application, database, parent_id, run)
            pg.require(state["State"]["Running"], "fresh application exited")
            health = subprocess.run(
                [
                    "docker",
                    "exec",
                    application,
                    "curl",
                    "-fsS",
                    "--max-time",
                    "3",
                    "http://127.0.0.1:8080/health",
                ],
                stdout=subprocess.PIPE,
                stderr=pg.PRIVATE,
                timeout=10,
            )
            if health.returncode == 0:
                break
            time.sleep(2)
        else:
            raise RuntimeError("fresh app startup timeout")
        pg.require(
            pg.sql(database, "SELECT version,dirty FROM schema_migrations;") == "134|f",
            "fresh schema migration incomplete",
        )
        pg.require(
            pg.sql(database, "SELECT count(*) FROM knowledges;") == "0",
            "test database contains documents before probe",
        )
        print(
            "=== 3/4 启动隔离浏览器 UI，仅预置共享连接 ==="
            if args.kap_model_ui
            else "=== 3/4 新模型接入：共用凭据、真实能力验证及用途接入 ==="
            if args.kap_model_registry
            else "=== 3/4 虚构资料：真实模型、纯向量召回、上传、删除及重新解析 ===",
            flush=True,
        )
        create(
            tester,
            "--network",
            "container:" + database,
            "--memory",
            "2g" if args.kap_upload_flow else "1g",
            "--cpus",
            "1",
            "--user",
            "0:0",
            "--workdir",
            "/probe",
            "--entrypoint",
            "python",
            "-e",
            "HTTPS_PROXY=" + proxy,
            "-e",
            "HTTP_PROXY=" + proxy,
            "-e",
            "NO_PROXY=127.0.0.1,localhost",
            *workspace_env_args(args.aliyun_workspace_id),
            "--mount",
            f"type=bind,src={repo},dst=/probe,readonly",
            "--mount",
            f"type=bind,src={stage},dst=/evidence",
            kap["Image"],
            "/probe/scripts/weknora_model_registry_probe.py"
            if args.kap_model_registry
            else "/probe/scripts/weknora_live_probe.py",
        )
        if args.kap_model_ui:
            create(
                relay,
                "--network",
                outside,
                "-p",
                f"127.0.0.1:{args.ui_port}:18443",
                "--read-only",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges",
                "--memory",
                "128m",
                "--cpus",
                "0.5",
                "--entrypoint",
                "python",
                kap["Image"],
                "-c",
                (repo / "scripts/weknora_ui_relay.py").read_text(),
                database,
            )
            pg.docker("network", "connect", internal, relay)
            pg.docker("start", relay)
            wait_ui_session(
                tester,
                database,
                gateway,
                relay,
                internal,
                outside,
                stage,
                run,
                before,
                args.ui_port,
                args.ui_minutes,
            )
        else:
            subprocess.run(
                ["docker", "start", "-a", tester],
                stdout=pg.PRIVATE,
                stderr=pg.PRIVATE,
                timeout=3600 if args.kap_role_flows else 1800,
                check=True,
            )
        pg.require(pg.inspect(tester)["State"]["ExitCode"] == 0, "live probe failed")
        assert_shared_hosts(pg.inspect(tester), pg.inspect(database))
        report = json.loads((stage / "live-report.json").read_text())
        pg.require(
            report.get("preparation_and_session_completed" if args.kap_model_ui else "passed")
            is True,
            "live report failed",
        )
        if args.kap_upload_flow:
            pg.require(
                report.get("kap_role_authorization", {}).get("upload_workflow_passed") is True,
                "KAP upload workflow not passed",
            )
        print(json.dumps(report, ensure_ascii=False), flush=True)
        assert_network(pg.inspect(database), [internal], run)
        if args.kap_model_ui:
            assert_network(pg.inspect(relay), [internal, outside], run, ui_port=args.ui_port)
        assert_network(pg.inspect(gateway), [internal, outside], run)
        print("=== 4/4 核对生产未变并停止全部测试容器 ===", flush=True)
        pg.compare(before, app.production_fingerprint())
        code = 0
    except Exception:
        pg.PRIVATE.write(traceback.format_exc().encode())
        print_report_if_readable(stage)
        print("联网演练停止，生产未切换；不要粘贴 private 文件。", flush=True)
    finally:
        for name in reversed(created):
            try:
                item = pg.inspect(name)
                pg.require(
                    item["Config"].get("Labels", {}).get(pg.LABEL) == str(run),
                    "cleanup label mismatch",
                )
                subprocess.run(
                    ["docker", "logs", "--tail", "100", name],
                    stdout=pg.PRIVATE,
                    stderr=pg.PRIVATE,
                    timeout=15,
                )
                pg.docker("stop", "-t", "30", name)
            except Exception:
                code = 1
                print("测试容器收尾需检查：" + name, flush=True)
        if before:
            try:
                pg.compare(before, app.production_fingerprint())
            except Exception:
                code = 1
        if code == 0:
            if args.kap_model_ui:
                (stage / "UI-SESSION-CLOSED").write_text(
                    "Session stopped; production fingerprint unchanged; manual browser acceptance is separate.\n"
                )
            elif args.kap_model_registry:
                (stage / "PASS-KAP-MODEL-REGISTRY").write_text(
                    "Live shared-connection onboarding passed; production unchanged; see live-report.json.\n"
                )
            else:
                (stage / "PASS-LIVE").write_text(
                    "Synthetic model/file lifecycle passed. See live-report.json for exact scope and exclusions.\n"
                )
            if args.kap_role_flows:
                (stage / "PASS-KAP-ROLES").write_text(
                    "HTTPS three-role authorization passed; see kap-role-report.json for exclusions.\n"
                )
            if args.kap_upload_flow:
                (stage / "PASS-KAP-UPLOAD").write_text(
                    "KAP asynchronous Markdown intake, personal confirmation and reviewed project publication passed.\n"
                )
        (stage / "exit-code").write_text(str(code) + "\n")
        lock.close()
        pg.PRIVATE.close()
        print(f"联网演练退出码：{code}；记录目录：{stage}", flush=True)
    raise SystemExit(code)


if __name__ == "__main__":
    main()
