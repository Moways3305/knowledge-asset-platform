"""Deploy the accepted main revision to the inventoried KAP stack, with a cold rollback boundary.

Application source is pinned independently from this delivery helper. No WeKnora
service/configuration is changed. Recovery after consumers or ports open must not
restore old business data. All detailed runtime and database evidence is private.
"""

import argparse
import base64
import copy
import json
import os
from pathlib import Path
import signal
import time
import traceback

from execute_production_cutover import escape_compose, sql, table_snapshot, wait_database
from prepare_production_release import Runner, fingerprint, preserve_rollback_image, require
from prepare_vision_fix import build_command, verify_images
from production_cutover_inventory import environment, storage_inventory, storage_summary
from production_cutover_runtime import Engine, LABEL, Runtime, endpoints, payload
from rollout_vision_fix import public_health, write

REVISION = "309e75d5e802aed2d152785b173db5e7c507f95d"
BASELINE = "36fb851aa3e940cba0e877bf7c3429b6ba4c1d56"
VERSION = "v1.1.0"
SCHEMA = "0088_outbox_consumption"
REPO = Path("/data/kap/repo")
ROOT = Path("/data/kap/release-preparations")
ORIGIN = "https://kap.moways.com.cn"
INFRA = ("kap-postgres-1", "kap-redis-1")
CONSUMERS = (
    "kap-worker-1",
    "kap-ocr_worker-1",
    "kap-parse_worker-1",
    "kap-notification_worker-1",
)
ADDED = ("kap-parse_worker-1", "kap-notification_worker-1")
ORIGINAL_START = (
    *INFRA,
    "kap-backend-1",
    "kap-worker-1",
    "kap-ocr_worker-1",
    "kap-beat-1",
    "kap-frontend-1",
)
START = (*INFRA, "kap-backend-1", *CONSUMERS, "kap-beat-1", "kap-frontend-1")
STOP_APPS = ("kap-frontend-1", "kap-backend-1", "kap-beat-1", "kap-worker-1", "kap-ocr_worker-1")
COMMANDS = {
    "worker": "celery -A app.worker.celery_app.celery_app worker --loglevel=INFO --queues=default --hostname=default@%h --prefetch-multiplier=1 --concurrency=2 --max-tasks-per-child=20 --max-memory-per-child=524288".split(),
    "parse_worker": "celery -A app.worker.celery_app.celery_app worker --loglevel=INFO --queues=parse --hostname=parse@%h --pool=prefork --concurrency=1 --prefetch-multiplier=1 --max-tasks-per-child=100 --max-memory-per-child=262144".split(),
    "notification_worker": "celery -A app.worker.celery_app.celery_app worker --loglevel=INFO --queues=notifications --hostname=notifications@%h --pool=prefork --concurrency=1 --prefetch-multiplier=1 --max-tasks-per-child=100 --max-memory-per-child=262144".split(),
}
RESOURCES = {
    "worker": (1_000_000_000, 3072),
    "parse_worker": (250_000_000, 512),
    "notification_worker": (500_000_000, 512),
}


def git(r, *args, timeout=60):
    return r.capture(
        "git", "-c", "safe.directory=" + str(REPO), "-C", str(REPO), *args, timeout=timeout
    )


def wait_healthy(r, names):
    deadline = time.monotonic() + 240
    while time.monotonic() < deadline:
        states = [r.inspect(n)["State"] for n in names]
        if all(x["Running"] and x.get("Health", {}).get("Status") == "healthy" for x in states):
            return
        if any(x.get("Dead") or x.get("OOMKilled") for x in states):
            raise RuntimeError("service_health_failed")
        time.sleep(2)
    raise RuntimeError("service_health_timeout")


def unchanged(r, old):
    for name, previous in old.items():
        item = r.inspect(name)
        require(
            fingerprint(item) == fingerprint(previous) and endpoints(item) == endpoints(previous),
            "runtime_changed",
        )
        require(item["State"]["Running"] == previous["State"]["Running"], "runtime_state_changed")


def validate_inventory(r, directory):
    report = json.loads((directory / "report.json").read_text())
    old = json.loads((directory / "runtime-private.json").read_text())
    require(
        report.get("running_release") == {"version": "v1.0.1", "commit": BASELINE},
        "unexpected_release",
    )
    require(
        report.get("migration") == "0083_model_registry" and report.get("repository_clean") is True,
        "unexpected_inventory",
    )
    require(
        set(old)
        == set(ORIGINAL_START)
        | {"kap-migrate-1"}
        | {"WeKnora-" + s for s in ("app", "frontend", "docreader", "postgres", "redis")},
        "unexpected_container_set",
    )
    unchanged(r, old)
    live = r.docker("ps", "-a", "--format", "{{.Names}}").splitlines()
    require(not any(n in live for n in ADDED), "new_consumer_already_exists")
    require(
        git(r, "rev-parse", "HEAD") == BASELINE and not git(r, "status", "--porcelain"),
        "production_checkout_changed",
    )
    git(r, "merge-base", "--is-ancestor", BASELINE, REVISION)
    require(
        sql(r, old[INFRA[0]], "SELECT version_num FROM alembic_version;") == "0083_model_registry",
        "schema_changed",
    )
    require(
        sql(
            r,
            old[INFRA[0]],
            "SELECT count(*) FROM pg_tablespace WHERE spcname NOT IN ('pg_default','pg_global');",
        )
        == "0",
        "external_tablespace_requires_backup_plan",
    )
    r.docker(
        "exec",
        "kap-postgres-1",
        "sh",
        "-ec",
        'test -d "$PGDATA"; test ! -L "$PGDATA"; test ! -L "$PGDATA/pg_wal"',
    )
    for name in ORIGINAL_START:
        require(old[name]["State"]["Running"], "old_service_stopped")
        require(
            r.image_identity(old[name]["Image"]) == old[name]["Image"], "rollback_image_missing"
        )
    apps = [old[n] for n in ORIGINAL_START if n not in INFRA and n != "kap-frontend-1"]
    backend_env = environment(old["kap-backend-1"])
    for app in apps:
        env = environment(app)
        require(
            all(
                env.get(k) == backend_env.get(k)
                for k in (
                    "DATABASE_URL",
                    "POSTGRES_PASSWORD",
                    "REDIS_URL",
                    "CELERY_BROKER_URL",
                    "WEKNORA_BASE_URL",
                    "WEKNORA_API_KEY",
                )
            ),
            "service_environment_mismatch",
        )
        require(env.get("CELERY_TASK_ALWAYS_EAGER", "").lower() == "false", "eager_tasks_enabled")
        require(
            env.get("CELERY_DEFAULT_QUEUE", "default") == "default"
            and env.get("CELERY_OCR_QUEUE", "ocr") == "ocr",
            "custom_queue_requires_review",
        )
    public_health(r, old["kap-backend-1"]["Id"], BASELINE, "v1.0.1")
    return old


def deployment_configs(r, old, images, out):
    configs = {}
    for name in START:
        service = name[4:-2]
        template = copy.deepcopy(old["kap-worker-1"] if name in ADDED else old[name])
        if name in ADDED:
            template["Name"] = "/" + name
            for endpoint in template["NetworkSettings"]["Networks"].values():
                endpoint["Aliases"] = [service, name]
                endpoint["IPAMConfig"] = None
        image = (
            template["Image"]
            if name in INFRA
            else images["frontend" if service == "frontend" else "backend"]
        )
        previous = json.loads(r.docker("image", "inspect", template["Image"]))[0]["Config"]
        current = json.loads(r.docker("image", "inspect", image))[0]["Config"]
        config = payload(template, image, current, previous, out.name)
        config["Hostname"] = ""
        config["Labels"].update(
            {
                "com.docker.compose.project": "kap",
                "com.docker.compose.service": service,
                "com.docker.compose.project.working_dir": str(out),
                "com.docker.compose.project.config_files": str(out / "kap-compose-private.json"),
                "com.docker.compose.image": image,
            }
        )
        config["Labels"].pop("com.docker.compose.config-hash", None)
        if name not in INFRA and service != "frontend":
            env = dict(x.split("=", 1) for x in config["Env"])
            env.update(CELERY_PARSE_QUEUE="parse", CELERY_NOTIFICATION_QUEUE="notifications")
            config["Env"] = [k + "=" + v for k, v in env.items()]
        if service in COMMANDS:
            config["Cmd"] = COMMANDS[service]
            queue = {
                "worker": "default",
                "parse_worker": "parse",
                "notification_worker": "notifications",
            }[service]
            config["Healthcheck"] = {
                "Test": [
                    "CMD-SHELL",
                    "celery -A app.worker.celery_app.celery_app inspect ping --destination="
                    + queue
                    + "@$HOSTNAME || exit 1",
                ],
                "Interval": 30_000_000_000,
                "Timeout": 10_000_000_000,
                "Retries": 5,
                "StartPeriod": 30_000_000_000,
            }
            config["StopTimeout"] = 45 if service == "parse_worker" else 150
            cpu, memory = RESOURCES[service]
            config["HostConfig"].update(
                NanoCpus=cpu,
                Memory=memory * 1024**2,
                MemoryReservation=0,
                MemorySwap=2 * memory * 1024**2,
                CpuPeriod=0,
                CpuQuota=0,
            )
        if name in ADDED:
            config["HostConfig"]["Mounts"] = []
            config["HostConfig"]["PortBindings"] = {}
            config.pop("Volumes", None)
        configs[name] = config
    return configs


def operational_compose(r, old, configs, out):
    # Use resolved historical configuration only as a scaffold; replace all
    # identity/environment/mount/network/command/resource values from actual runtime.
    resolved = {}
    output = {"name": "kap", "services": {}, "volumes": {}, "networks": {}}
    for name, config in configs.items():
        prior = old["kap-worker-1"] if name in ADDED else old[name]
        labels = prior["Config"]["Labels"]
        files = labels["com.docker.compose.project.config_files"]
        if files not in resolved:
            command = ["compose", "-p", "kap"]
            for p in files.split(","):
                require(Path(p).is_file(), "compose_source_missing")
                command.extend(["-f", p])
            resolved[files] = json.loads(r.docker(*command, "config", "--format", "json"))
        service = copy.deepcopy(resolved[files]["services"][labels["com.docker.compose.service"]])
        for key in (
            "build",
            "depends_on",
            "profiles",
            "env_file",
            "extends",
            "pull_policy",
            "hostname",
            "labels",
            "mem_limit",
            "mem_reservation",
            "memswap_limit",
            "cpus",
            "cpu_quota",
            "cpu_period",
        ):
            service.pop(key, None)
        service.update(
            image=config["Image"],
            container_name=name,
            command=config.get("Cmd"),
            entrypoint=config.get("Entrypoint"),
            user=config.get("User", ""),
            working_dir=config.get("WorkingDir", ""),
            environment=dict(x.split("=", 1) for x in config["Env"]),
            restart=prior["HostConfig"]["RestartPolicy"]["Name"],
            ports=[],
            volumes=[],
            networks={},
        )
        host = config["HostConfig"]
        service["deploy"] = {
            "resources": {
                "limits": {"cpus": str(host["NanoCpus"] / 1e9), "memory": str(host["Memory"])}
            }
        }
        service["shm_size"] = str(host["ShmSize"])
        if host.get("MemorySwap"):
            service["memswap_limit"] = str(host["MemorySwap"])
        if "StopTimeout" in config:
            service["stop_grace_period"] = str(config["StopTimeout"]) + "s"
        if service.get("healthcheck") is not None:
            service.pop("healthcheck")
        if config.get("Healthcheck"):
            hc = config["Healthcheck"]
            service["healthcheck"] = {"test": hc["Test"]}
            for a, b in (
                ("Interval", "interval"),
                ("Timeout", "timeout"),
                ("StartPeriod", "start_period"),
                ("StartInterval", "start_interval"),
            ):
                if hc.get(a):
                    service["healthcheck"][b] = str(hc[a]) + "ns"
            if "Retries" in hc:
                service["healthcheck"]["retries"] = hc["Retries"]
        for network, ep in config["NetworkingConfig"]["EndpointsConfig"].items():
            require(not ep.get("IPAMConfig"), "static_network_requires_review")
            output["networks"][network] = {"external": True, "name": network}
            service["networks"][network] = {"aliases": ep.get("Aliases") or []}
        for mount in host["Mounts"]:
            m = {
                "type": mount["Type"],
                "source": mount["Source"],
                "target": mount["Target"],
                "read_only": mount["ReadOnly"],
            }
            if mount["Type"] == "volume":
                output["volumes"][mount["Source"]] = {"external": True, "name": mount["Source"]}
                m["volume"] = {"nocopy": True}
            elif mount.get("BindOptions", {}).get("Propagation"):
                m["bind"] = {"propagation": mount["BindOptions"]["Propagation"]}
            service["volumes"].append(m)
        for port, bindings in (
            {} if name in ADDED else prior["HostConfig"].get("PortBindings") or {}
        ).items():
            target, protocol = port.split("/")
            for binding in bindings or []:
                service["ports"].append(
                    {
                        "target": int(target),
                        "published": binding["HostPort"],
                        "host_ip": binding.get("HostIp", ""),
                        "protocol": protocol,
                    }
                )
        output["services"][name[4:-2]] = service
    path = out / "kap-compose-private.json"
    write(path, escape_compose(output))
    rendered = json.loads(
        r.docker("compose", "-p", "kap", "-f", str(path), "config", "--format", "json")
    )
    for service, expected in output["services"].items():
        actual = rendered["services"][service]
        env = actual["environment"]
        require(
            env == expected["environment"]
            or {k: v.replace("$$", "$") if isinstance(v, str) else v for k, v in env.items()}
            == expected["environment"],
            "compose_environment_changed",
        )
        require(actual["image"] == expected["image"], "compose_image_changed")
    return path


class StageRuntime(Runtime):
    def recover(self, order):
        require(
            not self.state["traffic_opening"],
            "traffic boundary crossed; automatic data rollback forbidden",
        )
        # Parent recovery removes replaced originals. Remove only this run's two
        # additional consumers too, including create-before-state-save crashes.
        for identity in self.r.docker(
            "ps", "-aq", "--filter", "label=" + LABEL + "=" + self.token
        ).splitlines():
            item = self.owned(identity)
            if item["Name"].lstrip("/") in ADDED:
                require(not item["State"]["Running"], "unexpected_consumer_started_before_boundary")
                self.r.docker("rm", identity)
        super().recover(order)


def open_release(runtime, old, configs):
    # This boundary precedes ANY worker/beat execution as well as public ports.
    # External effects and new user writes must never be lost to snapshot recovery.
    runtime.state["traffic_opening"] = True
    runtime.save()
    for name in reversed(START):
        identity = runtime.state["new"][name]
        if runtime.owned(identity)["State"]["Running"]:
            runtime.r.docker("stop", "-t", "120", identity, timeout=150)
    for name in START:
        config = copy.deepcopy(configs[name])
        prior = old["kap-worker-1"] if name in ADDED else old[name]
        config["HostConfig"]["RestartPolicy"] = copy.deepcopy(prior["HostConfig"]["RestartPolicy"])
        config["HostConfig"]["PortBindings"] = (
            {} if name in ADDED else copy.deepcopy(prior["HostConfig"].get("PortBindings") or {})
        )
        runtime.remove_new(name)
        runtime.create(name, config)
        runtime.start(name)
        if name == INFRA[0]:
            wait_database(runtime.r, old[name])
        wait_healthy(runtime.r, [name])


def execute(r, inventory, out, report, holder):
    print("=== 1/5 核对生产与回退镜像，构建固定版本 ===", flush=True)
    old = validate_inventory(r, inventory)
    originals = {n: old[n] for n in ORIGINAL_START}
    excluded = {n: item for n, item in old.items() if n not in ORIGINAL_START}
    active = [r.inspect(i) for i in r.docker("ps", "-q").splitlines()]
    stores = storage_inventory(originals, active)
    require(not any(x["unknown_writers"] for x in stores), "unknown_storage_writer")
    for item in active:
        if item["Id"] not in {x["Id"] for x in originals.values()}:
            require(
                not (set(item["NetworkSettings"]["Networks"]) & {"kap_internal", "kap_web"}),
                "unknown_KAP_network_client",
            )
    sizes = storage_summary(r, stores)
    import shutil

    needed = max(30, 3 * sum(x["used_mib"] for x in sizes) / 1024)
    require(
        shutil.disk_usage(out).free / 1024**3 > needed
        and all(x["filesystem_free_gib"] > needed for x in sizes),
        "backup_disk_headroom",
    )
    saved = {n: preserve_rollback_image(r, n, item, out.name) for n, item in originals.items()}
    write(out / "rollback-images.json", saved)
    write(out / "runtime-private.json", old)
    write(out / "storage-private.json", stores)
    source = out / "source"
    source.mkdir()
    git(r, "archive", "--format=tar", "--output=" + str(out / "source.tar"), REVISION)
    r.execute(["tar", "-xf", str(out / "source.tar"), "-C", str(source)], timeout=120)
    manifest = {
        "version": VERSION,
        "commit": REVISION,
        "previous_commit": BASELINE,
        "title": "平台稳定性与任务处理优化",
        "notify_users": True,
        "entries": [
            {"kind": "improved", "text": "优化资料检索、上传处理及后台任务的稳定性和资源使用。"},
            {"kind": "fixed", "text": "改进任务中断恢复、重复处理防护和通知投递。"},
            {"kind": "improved", "text": "移除不再使用的微盘扫描入口。"},
        ],
    }
    write(out / "release-manifest.json", manifest)
    encoded = base64.b64encode(json.dumps(manifest, ensure_ascii=False).encode()).decode()
    images = {}
    for component in ("backend", "frontend"):
        print("构建：" + component, flush=True)
        tag = "kap-stage:" + out.name + "-" + component
        r.execute(build_command(component, source, tag, encoded), timeout=7200)
        images[component] = r.image_identity(tag)
    verify_images(r, images, manifest)
    write(out / "candidate-image-ids.json", images)
    configs = deployment_configs(r, old, images, out)
    managed = operational_compose(r, old, configs, out)
    write(out / "candidate-runtime-private.json", configs)
    unchanged(r, old)
    require(
        git(r, "rev-parse", "HEAD") == BASELINE and not git(r, "status", "--porcelain"),
        "production_checkout_changed",
    )
    require(
        shutil.disk_usage(out).free / 1024**3 > needed
        and all(x["filesystem_free_gib"] > needed for x in storage_summary(r, stores)),
        "backup_disk_headroom_after_build",
    )
    api = Engine(r.log)
    require(
        api.request("GET", "/info")["ID"] == r.docker("info", "--format", "{{.ID}}"),
        "docker_engine_mismatch",
    )
    runtime = StageRuntime(r, api, out, originals, images["backend"])
    holder.append(runtime)
    report["checkpoint"] = "stopping_writers"
    print("=== 2/5 关闭入口并等待旧任务退出，制作校验停写副本 ===", flush=True)
    runtime.freeze(STOP_APPS)
    require(
        sql(
            r,
            originals[INFRA[0]],
            "SELECT count(*) FROM pg_stat_activity WHERE backend_type='client backend' AND pid<>pg_backend_pid();",
        )
        == "0",
        "database_writer_remains",
    )
    columns, before = table_snapshot(r, originals[INFRA[0]])
    write(out / "database-before-private.json", {"columns": columns, "snapshot": before})
    runtime.freeze(INFRA)
    active = [r.inspect(i) for i in r.docker("ps", "-q").splitlines()]
    require(
        not any(x["unknown_writers"] for x in storage_inventory(originals, active)),
        "storage_writer_appeared",
    )
    runtime.backup(stores)
    report["consistent_backup_completed"] = True
    runtime.detach_originals()
    for name, config in configs.items():
        runtime.create(name, config)
    runtime.state["data_mutated"] = True
    runtime.save()
    report["checkpoint"] = "database_upgrade"
    print("=== 3/5 迁移至 0088 并核对原有数据，验证新版就绪 ===", flush=True)
    for name in INFRA:
        runtime.start(name)
    wait_database(r, originals[INFRA[0]])
    wait_healthy(r, INFRA)
    runtime.helper(
        ["python", "-m", "alembic", "upgrade", "head"],
        image=images["backend"],
        network="kap_internal",
        env=configs["kap-backend-1"]["Env"],
    )
    require(
        sql(r, originals[INFRA[0]], "SELECT version_num FROM alembic_version;") == SCHEMA,
        "migration_target_not_reached",
    )
    require(
        table_snapshot(r, originals[INFRA[0]], columns)[1] == before,
        "business_data_changed_during_migration",
    )
    runtime.start("kap-backend-1")
    runtime.start("kap-frontend-1")
    wait_healthy(r, ("kap-backend-1", "kap-frontend-1"))
    r.docker(
        "exec",
        "kap-backend-1",
        "python",
        "-c",
        "import json,urllib.request; "
        "r=lambda p:json.load(urllib.request.urlopen('http://127.0.0.1:8000'+p,timeout=15)); "
        "d=r('/health/release'); assert d['commit']=="
        + repr(REVISION)
        + " and d['version']=="
        + repr(VERSION)
        + "; "
        "r('/health/ready'); d=r('/health/config'); assert d.get('production_ready') is True and d.get('production_blockers')==[]",
    )
    r.docker(
        "exec", "kap-backend-1", "python", "-m", "app.commands.sync_release_notes", "--check-only"
    )
    unchanged(r, excluded)
    report["checkpoint"] = "opening_traffic"
    print("=== 4/5 启动全部新版消费者和正式入口，核对发布身份 ===", flush=True)
    open_release(runtime, old, configs)
    report["production_switched"] = True
    public_health(r, runtime.state["new"]["kap-backend-1"], REVISION, VERSION)
    r.docker(
        "exec",
        "kap-backend-1",
        "python",
        "-m",
        "app.commands.sync_release_notes",
        "--origin",
        ORIGIN,
        timeout=120,
    )
    unchanged(r, excluded)
    print("=== 5/5 更新运维镜像引用与源码，保留回退材料 ===", flush=True)
    image_roles = {n[4:-2]: configs[n]["Image"] for n in START if n not in INFRA}
    image_roles["migrate"] = images["backend"]
    runtime.configure_entrypoints([], managed, image_roles)
    require(
        git(r, "rev-parse", "HEAD") == BASELINE and not git(r, "status", "--porcelain"),
        "production_checkout_changed",
    )
    import pwd

    owner = pwd.getpwuid(REPO.stat().st_uid).pw_name
    r.capture(
        "runuser",
        "-u",
        owner,
        "--",
        "git",
        "-c",
        "safe.directory=" + str(REPO),
        "-C",
        str(REPO),
        "merge",
        "--ff-only",
        REVISION,
    )
    write(
        ROOT / "current-release.json",
        {
            "version": VERSION,
            "revision": REVISION,
            "managed_compose_file": str(managed),
            "record_directory": str(out),
        },
    )
    runtime.state["passed"] = True
    runtime.save()
    pending = []
    for name, previous in originals.items():
        try:
            item = r.inspect(previous["Id"])
            require(
                not item["State"]["Running"]
                and item["Name"] == "/" + name + "-previous-" + runtime.token[-10:]
                and item["Image"] == previous["Image"],
                "old_container_identity_changed",
            )
            r.docker("rm", item["Id"])
        except Exception:
            pending.append("retained_original:" + name)
    report.update(
        passed=True,
        checkpoint="complete",
        production_switched=True,
        version=VERSION,
        revision=REVISION,
        migration_target=SCHEMA,
        business_data_preserved=True,
        weknora_services_unchanged=True,
        model_configuration_changed=False,
        release_recorded=True,
        source_updated=True,
        managed_compose_file=str(managed),
        historical_migrate_retained=True,
        old_images_and_cold_copies_retained=True,
        post_deployment_tasks_pending=pending,
        worker_resources={k: {"cpu": v[0] / 1e9, "memory_mib": v[1]} for k, v in RESOURCES.items()},
    )


def validate_recovery_state(state, old, token):
    require(
        not state.get("passed") and not state.get("traffic_opening"),
        "traffic boundary crossed; automatic data rollback forbidden",
    )
    require(state["originals"] == {n: old[n] for n in ORIGINAL_START}, "recovery_originals_changed")
    mounts = [m for item in state["originals"].values() for m in item.get("Mounts", [])]
    for index, backup in enumerate(state["backups"]):
        require(
            backup["mount"] in mounts
            and backup["volume"] == "kap-cold-" + token[-10:] + "-" + str(index),
            "recovery_backup_target_changed",
        )


def recover_record(r, inventory, out):
    state = json.loads((out / "state-private.json").read_text())
    old = json.loads((inventory / "runtime-private.json").read_text())
    validate_recovery_state(state, old, out.name)
    images = json.loads((out / "candidate-image-ids.json").read_text())
    require(
        r.image_identity(images["backend"]) == images["backend"], "recovery_helper_image_missing"
    )
    runtime = object.__new__(StageRuntime)
    runtime.r, runtime.api, runtime.directory = r, Engine(r.log), out
    runtime.token, runtime.helper_image, runtime.state = out.name, images["backend"], state
    runtime.recover(ORIGINAL_START)
    wait_healthy(r, ORIGINAL_START)
    public_health(r, old["kap-backend-1"]["Id"], BASELINE, "v1.0.1")


def main():
    import fcntl

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--recover",
        action="store_true",
        help="Resume recovery only before workers or traffic were opened",
    )
    args = parser.parse_args()
    os.umask(0o077)
    inventory, out = args.inventory.resolve(strict=True), args.output.resolve(strict=True)
    require(
        inventory.parent == ROOT and out.parent == ROOT and out != inventory,
        "unexpected_record_directory",
    )
    report = {
        "phase": "production_stage_rollout",
        "passed": False,
        "production_switched": False,
        "raw_logs_included": False,
        "checkpoint": "preflight",
        "revision": REVISION,
        "version": VERSION,
    }
    holder = []
    with (ROOT / "deployment.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args.recover:
            recovery = {
                "phase": "production_stage_recovery",
                "passed": False,
                "raw_logs_included": False,
            }
            with (out / "private.log").open("ab") as log:
                try:
                    recover_record(Runner(log), inventory, out)
                    recovery.update(
                        passed=True, previous_release_recovered=True, production_switched=False
                    )
                except BaseException:
                    log.write(traceback.format_exc().encode())
                    recovery.update(
                        error="recovery_failed_or_refused_private_details_retained",
                        manual_recovery_required=True,
                    )
                write(out / "recovery-report.json", recovery)
                print(json.dumps(recovery, ensure_ascii=False, indent=2), flush=True)
            return 0 if recovery["passed"] else 1
        (out / "ATTEMPTED").open("x").close()
        with (out / "private.log").open("ab") as log:
            r = Runner(log)
            try:

                def interrupt(signum, frame):
                    raise RuntimeError("deployment_interrupted")

                signal.signal(signal.SIGTERM, interrupt)
                signal.signal(signal.SIGINT, interrupt)
                execute(r, inventory, out, report, holder)
            except BaseException:
                log.write(traceback.format_exc().encode())
                log.flush()
                report["error"] = "deployment_failed_private_details_retained"
                if holder:
                    runtime = holder[0]
                    report["production_switched"] = bool(runtime.state["traffic_opening"])
                    signal.signal(signal.SIGTERM, signal.SIG_IGN)
                    signal.signal(signal.SIGINT, signal.SIG_IGN)
                    if not runtime.state["traffic_opening"]:
                        print("开放入口和后台消费者前失败，恢复旧服务及本轮停写副本。", flush=True)
                        try:
                            runtime.recover(ORIGINAL_START)
                            wait_healthy(r, ORIGINAL_START)
                            public_health(
                                r,
                                runtime.state["originals"]["kap-backend-1"]["Id"],
                                BASELINE,
                                "v1.0.1",
                            )
                            report["previous_release_recovered"] = True
                        except BaseException:
                            log.write(traceback.format_exc().encode())
                            report.update(
                                previous_release_recovered=False, manual_recovery_required=True
                            )
                    else:
                        report.update(
                            manual_recovery_required=True, automatic_data_restore_skipped=True
                        )
                        print(
                            "后台任务或入口已开放；保留当前数据和现场，不自动恢复旧库，不要重复部署。",
                            flush=True,
                        )
            finally:
                write(out / "report.json", report)
                print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
                print("部署记录目录：" + str(out), flush=True)
    return 0 if report["passed"] and not report.get("post_deployment_tasks_pending") else 1


if __name__ == "__main__":
    raise SystemExit(main())
