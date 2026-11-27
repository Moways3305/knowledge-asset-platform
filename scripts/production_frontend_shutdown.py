"""Bound nginx draining without a SIGKILL or a change to persistent runtime settings."""

import json
import time

from prepare_production_release import require
from production_cutover_runtime import LABEL

FRONTEND = "kap-frontend-1"


def validate_frontend(item):
    config = item.get("Config", {})
    labels = config.get("Labels", {})
    require(
        item.get("Name") == "/" + FRONTEND
        and config.get("Cmd") == ["nginx", "-g", "daemon off;"]
        and config.get("Entrypoint") == ["/docker-entrypoint.sh"]
        and config.get("StopSignal") == "SIGQUIT"
        and labels.get("com.docker.compose.project") == "kap"
        and labels.get("com.docker.compose.service") == "frontend",
        "unexpected_frontend_runtime",
    )


def stop_frontend(runner, reference, *, token=None, grace=120, terminate_grace=30):
    validate_frontend(reference)
    identity = reference["Id"]

    def inspect():
        item = json.loads(runner.docker("inspect", identity, timeout=10))[0]
        validate_frontend(item)
        require(
            item.get("Id") == identity
            and item.get("Image") == reference["Image"]
            and (token is None or item["Config"]["Labels"].get(LABEL) == token),
            "frontend_identity_changed",
        )
        require(
            item.get("HostConfig", {}).get("RestartPolicy", {}).get("Name") == "no",
            "frontend_restart_not_disabled",
        )
        state = item["State"]
        require(
            not any(state.get(key) for key in ("OOMKilled", "Dead", "Paused", "Restarting")),
            "frontend_state_not_safe",
        )
        if not state["Running"]:
            require(state.get("ExitCode") == 0, "frontend_exit_not_clean")
        return state["Running"]

    def signal(name):
        if not inspect():
            return
        try:
            runner.docker("kill", "--signal=" + name, identity, timeout=10)
        except Exception:
            # Natural exit can race with the signal. Only an inspected clean
            # exit is success; identity errors and live-container failures escape.
            if inspect():
                raise

    def wait(seconds):
        started = time.monotonic()
        deadline, notice = started + seconds, started + 15
        while inspect():
            now = time.monotonic()
            if now >= deadline:
                return False
            if now >= notice:
                print(f"等待前端退出，已用时 {int(now - started)} 秒。", flush=True)
                notice = now + 15
            time.sleep(min(2, deadline - now))
        return True

    print("关闭前端新连接，最多等待 120 秒让现有请求结束。", flush=True)
    signal("QUIT")
    if wait(grace):
        return
    print("前端等待期结束，关闭剩余 HTTP 连接；后台任务继续按原流程停止。", flush=True)
    signal("TERM")
    require(wait(terminate_grace), "frontend_termination_timeout")
