"""CI: exercise baked release metadata in the actual backend/frontend Docker images."""

import argparse
import base64
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("component", choices=["backend", "frontend"])
    component = parser.parse_args().component
    manifest = {
        "version": "v1.2.3",
        "commit": "a" * 40,
        "previous_commit": "b" * 40,
        "title": "CI 隔离构建",
        "entries": [{"kind": "fixed", "text": "验证中文说明可完整写入镜像。"}],
        "notify_users": False,
    }
    encoded = base64.b64encode(json.dumps(manifest, ensure_ascii=False).encode()).decode()
    tag = f"kap-{component}-ci"
    build = ["docker", "build", "--build-arg", f"KAP_RELEASE_MANIFEST_B64={encoded}", "-t", tag]
    build.extend(["./backend"] if component == "backend" else ["-f", "Dockerfile.frontend", "."])
    subprocess.run(build, cwd=ROOT, check=True)
    if component == "backend":
        command = [
            "docker",
            "run",
            "--rm",
            "-e",
            "APP_VERSION=9.9.9",
            tag,
            "python",
            "-c",
            "import json; from app.core.release_manifest import load_manifest; from app.core.config import get_settings; m=load_manifest(); assert get_settings().app_version == '1.2.3'; print(json.dumps(m.model_dump(), ensure_ascii=False))",
        ]
        expected = manifest
    else:
        command = [
            "docker",
            "run",
            "--rm",
            "--entrypoint",
            "cat",
            tag,
            "/usr/share/nginx/html/release-identity.json",
        ]
        expected = {"version": manifest["version"], "commit": manifest["commit"]}
    actual = json.loads(subprocess.check_output(command, cwd=ROOT, encoding="utf-8"))
    if actual != expected:
        raise SystemExit("Baked release metadata does not match the build manifest")
    print(f"{component}: baked release metadata verified")


if __name__ == "__main__":
    main()
