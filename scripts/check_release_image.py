"""CI: exercise baked release metadata in the actual backend/frontend Docker images."""

import argparse
import base64
import json
import subprocess
import tarfile
import tempfile
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@contextmanager
def restricted_context(component: str):
    """Reproduce a restrictive Git checkout without chmod'ing the real working tree.

    Only tracked files enter the temporary archive; secrets and generated output do not.
    Docker still applies the context's .dockerignore. No archive is saved in the repo.
    """
    context_root = ROOT / "backend" if component == "backend" else ROOT
    names = subprocess.check_output(
        ["git", "ls-files", "-z", "--", "."], cwd=context_root, encoding="utf-8"
    ).split("\0")
    with tempfile.TemporaryFile() as stream:
        with tarfile.open(fileobj=stream, mode="w") as archive:
            directories = set()
            for name in filter(None, names):
                relative = Path(name)
                if any(part == ".env" or part.startswith(".env.") for part in relative.parts):
                    continue
                if component == "backend" and relative.parts[0] not in {
                    "Dockerfile",
                    "requirements.lock",
                    "pyproject.toml",
                    "alembic.ini",
                    "app",
                    "alembic",
                    ".dockerignore",
                }:
                    continue
                for parent in reversed(relative.parents):
                    if parent == Path(".") or parent in directories:
                        continue
                    directory = tarfile.TarInfo(parent.as_posix())
                    directory.type = tarfile.DIRTYPE
                    directory.mode = 0o700
                    archive.addfile(directory)
                    directories.add(parent)
                source = context_root / relative
                info = archive.gettarinfo(str(source), arcname=relative.as_posix())
                if not info.isfile():
                    raise ValueError(f"Only regular tracked build inputs are supported: {name}")
                info.mode = 0o600
                info.uid = info.gid = 0
                info.uname = info.gname = "root"
                with source.open("rb") as content:
                    archive.addfile(info, content)
        stream.seek(0)
        yield stream


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
    build.extend(["-f", "Dockerfile" if component == "backend" else "Dockerfile.frontend", "-"])
    with restricted_context(component) as stream:
        subprocess.run(build, cwd=ROOT, stdin=stream, check=True)
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
            "import json,os; from pathlib import Path; assert os.geteuid() != 0; import app.models; import app.main; import app.commands.sync_release_notes; from app.core.release_manifest import load_manifest; from app.core.config import get_settings; Path('/app/alembic.ini').read_text(); Path('/app/alembic/env.py').read_text(); files=list(Path('/app/alembic/versions').glob('*.py')); assert files; [p.read_text() for p in files]; m=load_manifest(); assert get_settings().app_version == '1.2.3'; print(json.dumps(m.model_dump(), ensure_ascii=False))",
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
    if component == "frontend":
        subprocess.run(["docker", "run", "--rm", tag, "nginx", "-t"], cwd=ROOT, check=True)
    print(f"{component}: baked release metadata verified")


if __name__ == "__main__":
    main()
