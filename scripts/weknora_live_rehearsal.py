"""Fresh synthetic database with a two-domain egress gateway; never switches production."""

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import secrets
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


def assert_network(item, expected, run):
    pg.require(
        item["Config"].get("Labels", {}).get(pg.LABEL) == str(run), "resource label mismatch"
    )
    pg.require(not item["HostConfig"].get("PortBindings"), "published ports forbidden")
    pg.require(not item["HostConfig"].get("Privileged"), "privileged container forbidden")
    pg.require(
        set(item["NetworkSettings"]["Networks"]) == set(expected), "network attachment changed"
    )


def prepare_fixture_models(model_rows, *, correct_rerank_endpoint=False, workspace_id=""):
    """Explicit, narrow correction in synthetic records only; never mutate the snapshot."""
    models = copy.deepcopy(model_rows)
    adjustments = []
    pg.require(not (correct_rerank_endpoint and workspace_id), "choose one fixture adjustment mode")
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
    args = parser.parse_args()
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
    created = []
    before, code = None, 1
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
        )
        if adjustments:
            print("仅调整本轮虚构模型的地址；生产配置未修改，须后续单独验收。", flush=True)
        (stage / "live-private.json").write_text(
            json.dumps(
                {
                    "models": model_rows,
                    "aes_key": snapshot["aes_key"],
                    "generation": picked["generation"],
                    "configuration_adjustments": adjustments,
                }
            )
        )
        password = secrets.token_urlsafe(32)
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
        print("=== 3/4 虚构资料：真实模型、纯向量召回、上传、删除及重新解析 ===", flush=True)
        create(
            tester,
            "--network",
            "container:" + database,
            "--memory",
            "1g",
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
            "/probe/scripts/weknora_live_probe.py",
        )
        subprocess.run(
            ["docker", "start", "-a", tester],
            stdout=pg.PRIVATE,
            stderr=pg.PRIVATE,
            timeout=1800,
            check=True,
        )
        pg.require(pg.inspect(tester)["State"]["ExitCode"] == 0, "live probe failed")
        assert_shared_hosts(pg.inspect(tester), pg.inspect(database))
        report = json.loads((stage / "live-report.json").read_text())
        pg.require(report.get("passed") is True, "live report failed")
        print(json.dumps(report, ensure_ascii=False), flush=True)
        assert_network(pg.inspect(database), [internal], run)
        assert_network(pg.inspect(gateway), [internal, outside], run)
        print("=== 4/4 核对生产未变并停止全部测试容器 ===", flush=True)
        pg.compare(before, app.production_fingerprint())
        code = 0
    except Exception:
        pg.PRIVATE.write(traceback.format_exc().encode())
        if (stage / "live-report.json").is_file():
            print((stage / "live-report.json").read_text(), flush=True)
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
            (stage / "PASS-LIVE").write_text(
                "Synthetic model/file lifecycle passed; role flows, multimodal and PDF/OCR NOT accepted.\n"
            )
        (stage / "exit-code").write_text(str(code) + "\n")
        lock.close()
        pg.PRIVATE.close()
        print(f"联网演练退出码：{code}；记录目录：{stage}", flush=True)
    raise SystemExit(code)


if __name__ == "__main__":
    main()
