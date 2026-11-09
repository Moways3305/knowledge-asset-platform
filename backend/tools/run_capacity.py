"""Host-side bounded load driver; run after the isolated Compose stack is ready.

python backend/tools/run_capacity.py --image YOUR_BACKEND_IMAGE --output ABSOLUTE_DIR
The stack must use deploy/compose.capacity-test.yml and project kap-capacity-local.
Does not deploy, stop or modify other stacks. Captures Docker resource samples and
closed-loop latency reports; stops escalating after errors or a clear latency knee.
"""

import argparse
import hashlib
import json
import os
import subprocess
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROJECT = "kap-capacity-local"
COMPOSE = ["docker", "compose", "-p", PROJECT, "-f", str(ROOT / "deploy/compose.capacity-test.yml")]


def execute(args):
    return subprocess.check_output(args, text=True, encoding="utf-8", errors="replace")


def resources(stop, output):
    with output.open("w", encoding="utf-8") as stream:
        while not stop.is_set():
            ids = execute(
                ["docker", "ps", "-q", "--filter", f"label=com.docker.compose.project={PROJECT}"]
            ).split()
            if ids:
                result = subprocess.run(
                    ["docker", "stats", "--no-stream", "--format", "{{json .}}", *ids],
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
                # A short-lived probe may disappear between ps and stats. Mark
                # missing samples explicitly, never report zero resource use.
                stream.write(
                    json.dumps(
                        {
                            "time": time.time(),
                            "sampling_error": result.returncode != 0,
                            "containers": [
                                json.loads(line)
                                for line in result.stdout.splitlines()
                                if line.startswith("{")
                            ],
                        }
                    )
                    + "\n"
                )
                stream.flush()
            stop.wait(2)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--kind", choices=["login", "list", "search", "mixed"], default="mixed")
    parser.add_argument("--seconds", type=int, choices=range(5, 121), default=30)
    parser.add_argument("--levels", type=int, nargs="+", default=[1, 4, 8, 16, 32, 64])
    parser.add_argument("--login-history", type=int, choices=[0, 20000], default=0)
    parser.add_argument(
        "--label", choices=["baseline", "fixed", "slow", "timeout"], default="baseline"
    )
    args = parser.parse_args()
    if not args.output.is_absolute() or any(level < 1 or level > 128 for level in args.levels):
        parser.error("Use an absolute output directory and concurrency 1..128")
    os.environ["KAP_CAPACITY_IMAGE"] = args.image
    network = json.loads(execute(["docker", "network", "inspect", PROJECT + "_default"]))[0]
    assert network["Internal"], "Refusing a stack with external network access"
    api = json.loads(execute(["docker", "inspect", PROJECT + "-api-1"]))[0]
    assert not api["HostConfig"]["PortBindings"], "Refusing published API ports"
    assert "KAP_CAPACITY_ISOLATED=1" in api["Config"]["Env"]
    assert set(api["NetworkSettings"]["Networks"]) == {PROJECT + "_default"}
    mounted_app = next(mount for mount in api["Mounts"] if mount["Destination"] == "/app/app")
    assert Path(mounted_app["Source"]).resolve() == ROOT / "backend/app"
    assert not mounted_app["RW"]
    image = json.loads(execute(["docker", "image", "inspect", args.image]))[0]
    assert api["Image"] == image["Id"], "Probe and API must use the same runtime image"
    args.output.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    for path in sorted((ROOT / "backend/app").rglob("*.py")):
        digest.update(path.relative_to(ROOT).as_posix().encode())
        digest.update(path.read_bytes())
    metadata = {
        "revision": execute(["git", "-C", str(ROOT), "rev-parse", "HEAD"]).strip(),
        "app_tree_sha256": digest.hexdigest(),
        "runtime_image": image["Id"],
        "internal_network": True,
        "published_ports": False,
        "api_cpus": api["HostConfig"]["NanoCpus"] / 1e9,
        "api_memory_bytes": api["HostConfig"]["Memory"],
        "model_and_weknora": "controlled HTTP stand-ins; not a provider benchmark",
    }
    previous = None
    for level in args.levels:
        name = f"{args.label}-{args.kind}-{level}" + ("-history" if args.login_history else "")
        stop = threading.Event()
        thread = threading.Thread(
            target=resources, args=(stop, args.output / f"{name}-resources.jsonl")
        )
        thread.start()
        try:
            result = subprocess.run(
                COMPOSE
                + [
                    "run",
                    "--rm",
                    "--no-deps",
                    "probe",
                    "python",
                    "/probe/capacity_probe.py",
                    "load",
                    "--kind",
                    args.kind,
                    "--concurrency",
                    str(level),
                    "--seconds",
                    str(args.seconds),
                    "--label",
                    args.label,
                    "--login-history",
                    str(args.login_history),
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        finally:
            stop.set()
            thread.join(timeout=15)
        (args.output / f"{name}.log").write_text(result.stdout + result.stderr, encoding="utf-8")
        if result.returncode:
            raise SystemExit(f"Probe failed; see {args.output / (name + '.log')}")
        report = json.loads(result.stdout.strip().splitlines()[-1])
        report["environment"] = metadata
        (args.output / f"{name}.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(
            json.dumps({k: v for k, v in report.items() if k not in {"samples", "fixture"}}),
            flush=True,
        )
        knee = (
            previous
            and report["rps"] < previous["rps"] * 1.15
            and report["p95_ms"] > previous["p95_ms"] * 1.7
        )
        if sum(report["errors"].values()) or report["p95_ms"] > 5000 or knee:
            print(
                "Stopped escalation: errors, >5s P95, or rising latency without throughput gain.",
                flush=True,
            )
            break
        previous = report


if __name__ == "__main__":
    main()
