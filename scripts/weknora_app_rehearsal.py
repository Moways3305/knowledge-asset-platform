"""Start an offline WeKnora copy and run the real KAP client against it."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import time
import traceback
import uuid

import weknora_pg_upgrade_rehearsal as pg


def environment(item):
    return dict(line.split("=", 1) for line in item["Config"]["Env"] if "=" in line)


def write_env(path, values):
    pg.require(
        all("\n" not in value and "\r" not in value for value in values.values()),
        "multiline environment value",
    )
    path.write_text("".join(key + "=" + value + "\n" for key, value in values.items()))
    path.chmod(0o600)


def isolated_app_env(original):
    pg.require(
        len(original.get("SYSTEM_AES_KEY", "").encode()) == 32,
        "original AES key missing or invalid",
    )
    pg.require(
        original.get("STORAGE_TYPE", "local") == "local",
        "nonlocal file storage requires a separate rehearsal plan",
    )
    pg.require(
        original.get("RETRIEVE_DRIVER", "postgres") == "postgres",
        "additional retrievers require a separate rehearsal plan",
    )
    pg.require(
        original.get("DB_USER") and original.get("DB_PASSWORD"),
        "original database account unavailable",
    )
    # Allow-list, never inherit proxy settings, remote callbacks or external storage credentials.
    return {
        "SYSTEM_AES_KEY": original["SYSTEM_AES_KEY"],
        "JWT_SECRET": original.get("JWT_SECRET") or secrets.token_urlsafe(40),
        "DB_DRIVER": "postgres",
        "DB_HOST": "127.0.0.1",
        "DB_PORT": "5432",
        "DB_NAME": "WeKnora",
        "DB_USER": original["DB_USER"],
        "DB_PASSWORD": original["DB_PASSWORD"],
        "RETRIEVE_DRIVER": "postgres",
        "STORAGE_TYPE": "local",
        "LOCAL_STORAGE_BASE_DIR": "/data/files",
        "LOCAL_STORAGE_PATH_PREFIX": original.get("LOCAL_STORAGE_PATH_PREFIX", ""),
        "REDIS_ADDR": "127.0.0.1:6379",
        "REDIS_PASSWORD": "",
        "REDIS_DB": "0",
        "REDIS_PREFIX": "isolated-rehearsal",
        "DOCREADER_ADDR": "",
        "AUTO_MIGRATE": "false",
        "GIN_MODE": "release",
        "LOG_LEVEL": "warn",
        "LLM_DEBUG_LOG": "false",
        "DISABLE_REGISTRATION": "true",
        "NEO4J_ENABLE": "false",
        "LANGFUSE_ENABLED": "false",
        "WEKNORA_SANDBOX_DOCKER_ENABLED": "false",
        "WEKNORA_HOUSEKEEPING_ENABLED": "false",
        "WEKNORA_OUTBOUND_DIAL_TIMEOUT": "2s",
        "WEKNORA_AUDIT_RETENTION_DAYS": "0",
        "WEKNORA_ASYNQ_CORE_CONCURRENCY": "1",
        "WEKNORA_ASYNQ_POSTPROCESS_CONCURRENCY": "1",
        "WEKNORA_ASYNQ_ENRICHMENT_CONCURRENCY": "1",
        "WEKNORA_ASYNQ_MAINTENANCE_CONCURRENCY": "1",
        "WEKNORA_ASYNQ_SHARED_CONCURRENCY": "1",
        "WEKNORA_WIKI_ASYNQ_CONCURRENCY": "1",
    }


def guard_child(name, parent, parent_id, run):
    item = pg.inspect(name)
    pg.require(item["Config"]["Labels"].get(pg.LABEL) == str(run), "child label mismatch")
    pg.require(
        item["HostConfig"]["NetworkMode"] in {"container:" + parent, "container:" + parent_id},
        "child namespace mismatch",
    )
    pg.require(not item["HostConfig"].get("PortBindings"), "child publishes ports")
    return item


def production_fingerprint():
    result = {}
    for name in ["WeKnora-app", "WeKnora-postgres", "WeKnora-redis", "kap-backend-1"]:
        item = pg.inspect(name)
        result[name] = hashlib.sha256(
            json.dumps(
                {key: item[key] for key in ["Id", "Image", "Config", "Mounts"]}, sort_keys=True
            ).encode()
        ).hexdigest()
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rehearsal-dir", required=True, type=Path)
    args = parser.parse_args()
    import fcntl

    os.umask(0o077)
    run = args.rehearsal_dir.resolve(strict=True)
    pg.require(
        run.parent == Path("/data/weknora/upgrade-rehearsals")
        and run.name.startswith("run-")
        and run.name[4:].isalnum(),
        "unexpected rehearsal directory",
    )
    lock = (Path.home() / ".weknora-rehearsal.lock").open("a")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    candidates = [
        p
        for p in run.glob("schema090-*")
        if p.is_dir() and (p / "PASS").is_file() and (p / "exit-code").read_text().strip() == "0"
    ]
    pg.require(len(candidates) == 1, "expected exactly one successful schema rehearsal")
    source = candidates[0]
    pg.require(shutil.disk_usage(run).free > 20 * 1024**3, "less than 20 GiB free disk")
    repo = Path(__file__).resolve().parents[1]
    pg.require(
        (repo / "backend/app/services/weknora_client.py").is_file(), "KAP source package missing"
    )
    stage = run / ("app090-" + uuid.uuid4().hex[:10])
    stage.mkdir()
    pg.RUN, pg.STAGE = run, stage
    pg.PRIVATE = (stage / "private.log").open("ab")
    name = "wk-app090-" + uuid.uuid4().hex[:12]
    volume, files, skills = name + "-data", name + "-files", name + "-skills"
    app, redis, tester = name + "-app", name + "-redis", name + "-probe"
    parent_id = ""
    created = False
    production = None
    code = 1
    try:
        print("演练记录：" + str(stage), flush=True)
        resources = json.loads((source / "resources.json").read_text())
        images = json.loads((source / "images.json").read_text())
        source_name, source_volume = resources["container"], resources["volume"]
        pg.require(
            source_name.startswith("wk-schema090-") and source_volume == source_name + "-data",
            "invalid source names",
        )
        source_item = pg.guard(source_name, source_volume)
        pg.require(
            not source_item["State"]["Running"] and source_item["Image"] == images["database"],
            "source changed",
        )
        production = production_fingerprint()
        original = next(
            x
            for x in json.loads((run / "runtime-private.json").read_text())
            if x["Name"] == "/WeKnora-app"
        )
        original_env = environment(original)
        pg.require(
            environment(pg.inspect("WeKnora-app")).get("SYSTEM_AES_KEY")
            == original_env.get("SYSTEM_AES_KEY"),
            "production encryption key changed since backup",
        )
        app_env = isolated_app_env(original_env)
        kap = pg.inspect("kap-backend-1")
        kap_key = environment(kap).get("WEKNORA_API_KEY", "")
        pg.require(
            kap_key.startswith("sk-"), "KAP integration key unavailable in runtime environment"
        )
        redis_image = pg.inspect("WeKnora-redis")["Image"]
        bootstrap = dict(
            line.split("=", 1)
            for line in (run / "restore-private.env").read_text().splitlines()
            if "=" in line
        )
        pg.OWNER = bootstrap["POSTGRES_USER"]
        pg.require(
            pg.OWNER.startswith("wkrestore_") and pg.OWNER.replace("_", "").isalnum(),
            "invalid bootstrap user",
        )
        print("=== 1/5 复制数据库、文件和配置到新的隔离副本 ===", flush=True)
        # Recheck the original backup archives without echoing their contents.
        subprocess.run(
            ["sha256sum", "--check", "--status", "SHA256SUMS"],
            cwd=run,
            check=True,
            stdout=pg.PRIVATE,
            stderr=pg.PRIVATE,
            timeout=300,
        )
        for target in [volume, files, skills]:
            pg.docker("volume", "create", "--label", pg.LABEL + "=" + str(run), target)
        pg.docker(
            "run",
            "--rm",
            "--network",
            "none",
            "--user",
            "0:0",
            "--entrypoint",
            "sh",
            "--mount",
            f"type=volume,src={source_volume},dst=/from,readonly",
            "--mount",
            f"type=volume,src={volume},dst=/to",
            images["database"],
            "-c",
            "cp -a /from/. /to/",
        )
        for target, archive in [(files, "data-files.tar"), (skills, "preloaded-skills.tar")]:
            pg.docker(
                "run",
                "--rm",
                "--network",
                "none",
                "--user",
                "0:0",
                "--entrypoint",
                "sh",
                "--mount",
                f"type=bind,src={run / archive},dst=/backup.tar,readonly",
                "--mount",
                f"type=volume,src={target},dst=/restore",
                images["database"],
                "-c",
                "tar -xf /backup.tar -C /restore",
            )
        shutil.copyfile(run / "config/config.yaml", stage / "config.yaml")
        # Parent stage is 0700 on the host; the app's non-root UID must read the bind-mounted file.
        (stage / "config.yaml").chmod(0o644)
        write_env(stage / "app-private.env", app_env)
        (stage / "resources.json").write_text(
            json.dumps(
                {
                    "container": name,
                    "volume": volume,
                    "files": files,
                    "skills": skills,
                    "app": app,
                    "redis": redis,
                    "tester": tester,
                    "source_stage": str(source),
                    "run": str(run),
                },
                indent=2,
            )
        )
        (stage / "images.json").write_text(
            json.dumps({**images, "kap_runtime": kap["Image"], "redis": redis_image}, indent=2)
        )
        pg.docker(
            "run",
            "-d",
            "--name",
            name,
            "--label",
            pg.LABEL + "=" + str(run),
            "--network",
            "none",
            "--restart",
            "no",
            "--memory",
            "4g",
            "--cpus",
            "2",
            "--shm-size",
            "512m",
            "--env-file",
            str(run / "restore-private.env"),
            "--mount",
            f"type=volume,src={volume},dst=/var/lib/postgresql/data",
            images["database"],
        )
        created = True
        parent_id = pg.guard(name, volume)["Id"]
        pg.wait(name)
        pg.require(
            pg.sql(name, "SELECT version,dirty FROM schema_migrations;") == "134|f",
            "schema baseline changed",
        )
        # No historical Redis tasks are copied into the rehearsal.
        pg.docker(
            "run",
            "-d",
            "--name",
            redis,
            "--label",
            pg.LABEL + "=" + str(run),
            "--network",
            "container:" + name,
            "--restart",
            "no",
            "--memory",
            "256m",
            redis_image,
            "redis-server",
            "--bind",
            "127.0.0.1",
            "--save",
            "",
            "--appendonly",
            "no",
        )
        guard_child(redis, name, parent_id, run)
        for _ in range(30):
            ready = subprocess.run(
                ["docker", "exec", redis, "redis-cli", "ping"],
                stdout=subprocess.PIPE,
                stderr=pg.PRIVATE,
                timeout=10,
            )
            if ready.returncode == 0 and ready.stdout.strip() == b"PONG":
                break
            time.sleep(1)
        else:
            raise RuntimeError("isolated Redis startup timeout")
        print("=== 2/5 启动 v0.9.0，网络仅可访问隔离数据库与 Redis ===", flush=True)
        pg.docker(
            "run",
            "-d",
            "--name",
            app,
            "--label",
            pg.LABEL + "=" + str(run),
            "--network",
            "container:" + name,
            "--restart",
            "no",
            "--memory",
            "4g",
            "--cpus",
            "2",
            "--env-file",
            str(stage / "app-private.env"),
            "--mount",
            f"type=volume,src={files},dst=/data/files",
            "--mount",
            f"type=volume,src={skills},dst=/app/skills/preloaded",
            "--mount",
            f"type=bind,src={stage / 'config.yaml'},dst=/app/config/config.yaml,readonly",
            images["app"],
        )
        guard_child(app, name, parent_id, run)
        for _ in range(90):
            state = guard_child(app, name, parent_id, run)
            pg.require(state["State"]["Running"], "isolated app exited during startup")
            health = subprocess.run(
                [
                    "docker",
                    "exec",
                    app,
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
            raise RuntimeError("isolated app health timeout")
        print("=== 3/5 核验原密钥、原 KAP 凭证和实际客户端接口 ===", flush=True)
        stored = {}
        for table in ["models", "tenant_api_keys"]:
            stored[table] = json.loads(
                pg.sql(name, f"SELECT COALESCE(json_agg(t),'[]'::json) FROM public.{table} t;")
            )
        (stage / "probe-private.json").write_text(
            json.dumps(
                {
                    "aes_key": original_env["SYSTEM_AES_KEY"],
                    "api_key": kap_key,
                    "stored_records": stored,
                }
            )
        )
        (stage / "probe-private.json").chmod(0o600)
        pg.docker(
            "run",
            "--rm",
            "--name",
            tester,
            "--label",
            pg.LABEL + "=" + str(run),
            "--network",
            "container:" + name,
            "--user",
            "0:0",
            "--memory",
            "1g",
            "--cpus",
            "1",
            "--workdir",
            "/probe",
            "--entrypoint",
            "python",
            "--mount",
            f"type=bind,src={repo},dst=/probe,readonly",
            "--mount",
            f"type=bind,src={stage},dst=/evidence",
            kap["Image"],
            "/probe/scripts/weknora_app_probe.py",
        )
        report = json.loads((stage / "api-report.json").read_text())
        pg.require(report.get("passed") is True, "API report did not pass")
        print(json.dumps(report, ensure_ascii=False), flush=True)
        print("=== 4/5 重启应用并再次确认健康 ===", flush=True)
        pg.docker("restart", "-t", "30", app)
        for _ in range(90):
            guard_child(app, name, parent_id, run)
            health = subprocess.run(
                [
                    "docker",
                    "exec",
                    app,
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
            raise RuntimeError("app restart health timeout")
        pg.require(
            pg.sql(name, "SELECT version,dirty FROM schema_migrations;") == "134|f",
            "schema changed unexpectedly",
        )
        print("=== 5/5 核对生产容器未变并停止演练容器 ===", flush=True)
        pg.compare(production, production_fingerprint())
        code = 0
    except Exception:
        pg.PRIVATE.write(traceback.format_exc().encode())
        pg.PRIVATE.flush()
        if (stage / "api-report.json").is_file():
            print((stage / "api-report.json").read_text(), flush=True)
        print("演练停止，请只反馈进度日志；不要粘贴任何 private 文件。", flush=True)
    finally:
        for child in [tester, app, redis]:
            try:
                if pg.docker("ps", "-aq", "--filter", "name=^/" + child + "$"):
                    guard_child(child, name, parent_id, run)
                    subprocess.run(
                        ["docker", "logs", "--tail", "200", child],
                        stdout=pg.PRIVATE,
                        stderr=pg.PRIVATE,
                        timeout=15,
                    )
                    pg.docker("stop", "-t", "30", child)
            except Exception:
                code = 1
                print("隔离容器收尾需检查：" + child, flush=True)
        if created:
            try:
                pg.guard(name, volume)
                pg.docker("stop", "-t", "60", name)
            except Exception:
                code = 1
                print("隔离数据库收尾需检查：" + name, flush=True)
        if code == 0:
            (stage / "PASS-OFFLINE").write_text(
                "Offline app/API subset passed. Live model, vector API, upload/parse/delete/reparse and KAP role flows NOT accepted.\n"
            )
            print(
                "离线应用启动、原密钥和部分 KAP 接口验证通过。模型调用与文件处理闭环仍待验证；生产未切换。",
                flush=True,
            )
        (stage / "exit-code").write_text(str(code) + "\n")
        print(f"退出码：{code}；记录目录：{stage}", flush=True)
        pg.PRIVATE.close()
    raise SystemExit(code)


if __name__ == "__main__":
    main()
