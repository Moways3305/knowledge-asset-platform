"""Build and verify KAP's saved-vision fix; never replace a production container."""

import argparse
import base64
import json
import os
from pathlib import Path
import re
import uuid

from deploy_release import prepare
from execute_production_cutover import START
from prepare_production_release import fingerprint, require
from resume_production_build import ResumeRunner

ROOT = Path(__file__).resolve().parents[1]
BASELINE = "b85ca9816771e5bfdb964019546c542d5964e2b8"
EXPECTED = {
    "kap-backend-1": "sha256:f47a43f921655cc7bb29129c9baac23856b140d1c15230455ab2d880d80b06b2",
    "kap-frontend-1": "sha256:64da45819bf888edd70c9ca918ac1aff82cde53b7c04eaf468d327b8b36b809d",
    "WeKnora-app": "sha256:9b614bbb9ef9c8316acf886e94932cb7126103a421d1a7e6ba150307033b6a33",
}
PROBE = r"""
import asyncio, json, logging
from contextlib import redirect_stdout, redirect_stderr
from io import StringIO
from urllib.parse import urlsplit
logging.disable(logging.CRITICAL)
async def run():
    from app.core.config import get_settings
    from app.schemas.weknora_admin import ModelCheckRequest
    from app.services.weknora_client import WeKnoraClient
    from app.services import weknora_models as wm
    settings = get_settings()
    client = WeKnoraClient(base_url=settings.weknora_base_url, api_key=settings.weknora_api_key)
    rows = await client.list_models()
    checks = []
    for name in ('qwen3.6-plus', 'qwen3.5-omni-plus'):
        matches = [row for row in rows if row.get('name') == name]
        assert len(matches) == 1
        mid = str(matches[0]['id'])
        before = await client.get_model(mid)
        p = before.get('parameters') or {}
        endpoint = urlsplit(p.get('base_url', ''))
        assert before['type'] == 'VLLM' and before['source'] == 'remote'
        assert p.get('provider') == 'aliyun'
        assert endpoint.scheme == 'https' and endpoint.hostname in (
            'dashscope.aliyuncs.com', 'ws-47k0t1zmjgch8h33.cn-beijing.maas.aliyuncs.com')
        assert endpoint.path.rstrip('/') == '/compatible-mode/v1'
        result = await wm.check_model(client, ModelCheckRequest(model_ref=wm._model_ref(mid)), trace_id=None)
        after = await client.get_model(mid)
        checks.append({'model_name': name, 'passed': result.success is True,
                       'error_code': result.error_code if result.error_code in ('model_unavailable', 'model_test_timeout', 'vision_test_unavailable', 'credential_missing', 'credential_unconfirmed') else None,
                       'image_scope_confirmed': '图片理解测试通过' in result.message,
                       'saved_metadata_unchanged': before == after})
    return {'checks': checks, 'passed': all(c['passed'] and c['image_scope_confirmed'] and c['saved_metadata_unchanged'] for c in checks)}
try:
    with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
        result = asyncio.run(asyncio.wait_for(run(), 160))
except Exception:
    result = {'passed': False, 'diagnostic': 'candidate_vision_verification_failed'}
print(json.dumps(result))
"""


def build_command(component, source, tag, encoded):
    require(component in {"backend", "frontend"}, "unexpected build target")
    cmd = ["docker", "build", "--build-arg", "KAP_RELEASE_MANIFEST_B64=" + encoded, "-t", tag]
    if component == "backend":
        return cmd + [
            "--build-arg",
            "KAP_DEBIAN_MIRROR=https://mirrors.cloud.tencent.com/debian",
            "--build-arg",
            "KAP_DEBIAN_SECURITY_MIRROR=https://mirrors.cloud.tencent.com/debian-security",
            str(source / "backend"),
        ]
    return cmd + ["-f", str(source / "Dockerfile.frontend"), str(source)]


def verify_images(r, images, manifest):
    for component, image in images.items():
        path = (
            "/app/release-manifest.json"
            if component == "backend"
            else "/usr/share/nginx/html/release-identity.json"
        )
        identity = json.loads(
            r.docker("run", "--rm", "--network", "none", "--entrypoint", "cat", image, path)
        )
        require(
            identity.get("commit") == manifest["commit"]
            and identity.get("version") == manifest["version"],
            "candidate identity mismatch",
        )


def check_candidate(r, stage, image, backend):
    env_file = stage / "probe-env-private.txt"
    env = backend["Config"]["Env"]
    require(
        all("\n" not in value and "\r" not in value for value in env),
        "multiline environment unsupported",
    )
    env_file.write_text("\n".join(env) + "\n")
    name = "kap-vision-check-" + uuid.uuid4().hex[:10]
    identity = None
    try:
        identity = r.docker(
            "create",
            "--name",
            name,
            "--label",
            "kap.vision-preparation=" + stage.name,
            "--network",
            "container:" + backend["Id"],
            "--read-only",
            "--restart",
            "no",
            "--env-file",
            str(env_file),
            "-i",
            "--entrypoint",
            "python",
            image,
            "-",
        )
        result = json.loads(
            r.docker("start", "-a", "-i", identity, data=PROBE.encode(), timeout=180)
        )
        return result
    finally:
        env_file.unlink(missing_ok=True)
        if identity:
            item = r.inspect(identity)
            require(
                item["Name"] == "/" + name
                and item["Image"] == image
                and item["Config"]["Labels"].get("kap.vision-preparation") == stage.name,
                "verification container identity changed",
            )
            r.docker("rm", "-f", identity)


def main():
    import fcntl

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", required=True, type=Path)
    parser.add_argument("--revision", required=True)
    args = parser.parse_args()
    os.umask(0o077)
    stage = args.stage.resolve(strict=True)
    require(
        stage.parent == Path("/data/kap/vision-fix-preparations")
        and re.fullmatch(r"run-[A-Za-z0-9]{6}", stage.name),
        "unexpected preparation directory",
    )
    require(ROOT.resolve() == stage / "source", "unexpected source directory")
    require(re.fullmatch(r"[a-f0-9]{40}", args.revision), "full revision required")
    report = {
        "phase": "vision_fix_preparation",
        "passed": False,
        "production_switched": False,
        "raw_logs_included": False,
    }
    old = None
    with (
        (stage.parent / "prepare.lock").open("a") as lock,
        (stage / "private.log").open("ab") as log,
    ):
        r = ResumeRunner(log)
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            require(
                not r.capture("git", "status", "--porcelain", cwd=ROOT),
                "candidate source is not clean",
            )
            manifest = prepare("v1.0.1", BASELINE)
            require(manifest["commit"] == args.revision, "candidate source revision mismatch")
            print("=== 1/3 核对生产版本，记录当前容器 ===", flush=True)
            old = {name: r.inspect(name) for name in START}
            require(
                all(item["State"]["Running"] for item in old.values()),
                "production service not running",
            )
            require(
                all(old[name]["Image"] == expected for name, expected in EXPECTED.items()),
                "production images changed",
            )
            current = json.loads(
                r.docker(
                    "exec",
                    "kap-backend-1",
                    "python",
                    "-c",
                    "import json,urllib.request; print(json.dumps(json.load(urllib.request.urlopen('http://127.0.0.1:8000/health/release',timeout=10))))",
                )
            )
            require(current.get("commit") == BASELINE, "production release changed")
            (stage / "runtime-private.json").write_text(json.dumps(old))
            (stage / "release-manifest.json").write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2)
            )
            print("=== 2/3 构建 KAP 后端与前端候选镜像 ===", flush=True)
            encoded = base64.b64encode(json.dumps(manifest, ensure_ascii=False).encode()).decode()
            images = {}
            for component in ("backend", "frontend"):
                tag = "kap-vision-candidate:" + stage.name + "-" + component
                print("构建：" + component, flush=True)
                r.execute(build_command(component, ROOT, tag, encoded), cwd=ROOT, timeout=3600)
                images[component] = r.image_identity(tag)
                require(images[component] is not None, "candidate image missing")
            verify_images(r, images, manifest)
            (stage / "candidate-image-ids.json").write_text(json.dumps(images, indent=2))
            print("=== 3/3 临时容器验证修复后的图片测试入口 ===", flush=True)
            result = check_candidate(r, stage, images["backend"], old["kap-backend-1"])
            report.update(
                result,
                version=manifest["version"],
                revision=manifest["commit"],
                candidate_images=images,
            )
            require(result.get("passed") is True, "candidate vision verification failed")
            require(
                r.capture("git", "rev-parse", "HEAD", cwd=ROOT) == args.revision
                and not r.capture("git", "status", "--porcelain", cwd=ROOT),
                "candidate source changed",
            )
        except Exception:
            report.update(passed=False, error="preparation_failed_private_details_retained")
            import traceback

            log.write(traceback.format_exc().encode())
        finally:
            try:
                unchanged = old is not None and all(
                    fingerprint(r.inspect(name)) == fingerprint(item)
                    and r.inspect(name)["State"]["Running"]
                    for name, item in old.items()
                )
            except Exception:
                unchanged = False
            report["production_unchanged"] = unchanged
            report["passed"] = report["passed"] and unchanged
            if report["passed"]:
                (stage / "VERIFIED").write_text(args.revision + "\n")
            (stage / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
            print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
            print("补丁准备目录：" + str(stage), flush=True)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
