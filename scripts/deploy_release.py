"""Plan or execute a versioned Compose release. Default is read-only; no credentials in args."""

import argparse
import base64
import json
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
APPLICATION_SERVICES = ("backend", "worker", "ocr_worker", "beat", "frontend")
SERVICES = ("migrate", *APPLICATION_SERVICES)


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, encoding="utf-8").strip()


def prepare(version: str, previous: str) -> dict:
    if (
        not re.fullmatch(r"v?\d+\.\d+\.\d+(?:-[a-zA-Z0-9.-]+)?", version)
        or len(version.removeprefix("v")) > 39
    ):
        raise ValueError("版本号必须为 vX.Y.Z 或 vX.Y.Z-suffix")
    head = git("rev-parse", "HEAD")
    base = git("rev-parse", "--verify", "--end-of-options", previous + "^{commit}")
    subprocess.run(["git", "merge-base", "--is-ancestor", base, head], cwd=ROOT, check=True)
    if base == head:
        raise ValueError("基线与当前提交相同；重试登记请使用 --sync-only")
    paths = git(
        "diff", "--name-only", "--diff-filter=A", base, head, "--", "release-notes/*.json"
    ).splitlines()
    entries = []
    for path in paths:
        fragment = json.loads(git("show", f"{head}:{path}"))
        if not isinstance(fragment, list):
            raise ValueError("变更说明必须是条目数组")
        for entry in fragment:
            if (
                not isinstance(entry, dict)
                or set(entry) != {"kind", "text"}
                or entry["kind"] not in ("new", "improved", "fixed")
                or not isinstance(entry["text"], str)
                or not 1 <= len(entry["text"].strip()) <= 500
            ):
                raise ValueError("变更说明条目格式无效")
            if entry not in entries:
                entries.append(entry)
    if len(entries) > 50:
        raise ValueError("本次说明超过 50 条，请先合并整理，不能静默截断")
    if not entries:
        count = git("rev-list", "--count", f"{base}..{head}")
        entries = [
            {
                "kind": "improved",
                "text": f"本次部署包含 {count} 项代码提交，具体功能变化待审核补充。",
            }
        ]
    return {
        "version": "v" + version.removeprefix("v"),
        "title": "平台更新（待审核）",
        "entries": entries,
        "notify_users": True,
        "commit": head,
        "previous_commit": base,
    }


def verify_baseline(origin: str, manifest: dict, bootstrap: bool) -> None:
    request = urllib.request.Request(
        origin + "/health/release", headers={"Cache-Control": "no-cache"}
    )
    try:
        # A redirect must not silently select a different environment.
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                return None

        with urllib.request.build_opener(NoRedirect).open(request, timeout=20) as response:
            running = json.load(response)
    except urllib.error.HTTPError as exc:
        if bootstrap and exc.code == 404:
            return  # Explicit operator-selected baseline for a pre-feature deployment.
        raise ValueError("无法验证当前运行版本，未开始部署") from None
    if running is None and bootstrap:
        return
    if not isinstance(running, dict) or running.get("commit") != manifest["previous_commit"]:
        raise ValueError("--previous 必须匹配生产当前提交；重试同一部署请使用 --sync-only")


def execute(args, manifest: dict) -> None:
    origin = args.origin.rstrip("/")
    url = urlsplit(origin)
    if (
        url.scheme != "https"
        or not url.netloc
        or url.username
        or url.password
        or url.path
        or url.query
        or url.fragment
    ):
        raise ValueError("--origin 必须为生产用户入口 HTTPS origin")
    # Explicitly select the existing production stack, regardless of cwd or ambient env.
    compose = [
        "docker",
        "compose",
        "-p",
        "kap",
        "-f",
        "docker-compose.yml",
        "-f",
        "docker-compose.prod.yml",
    ]

    def run(*command: str) -> None:
        subprocess.run([*compose, *command], cwd=ROOT, check=True)

    if not args.sync_only:
        if not args.backup_confirmed:
            raise ValueError("请先完成数据库备份，再显式指定 --backup-confirmed")
        if git("status", "--porcelain"):
            raise ValueError("工作区不干净，不能把未提交文件部署成指定 Git 版本")
        verify_baseline(origin, manifest, args.bootstrap_baseline)
        encoded = base64.b64encode(json.dumps(manifest, ensure_ascii=False).encode()).decode()
        if len(encoded) > 24000:
            raise ValueError("发布说明过长，请精简后再构建（避免平台命令行长度限制）")
        if git("rev-parse", "HEAD") != manifest["commit"]:
            raise ValueError("Git 提交在准备期间发生变化，请重新预览")
        run("build", "--build-arg", f"KAP_RELEASE_MANIFEST_B64={encoded}", *SERVICES)
        if git("status", "--porcelain") or git("rev-parse", "HEAD") != manifest["commit"]:
            raise ValueError("构建期间代码发生变化，未更新服务；请重新构建")
        run("up", "-d", "--wait", "--wait-timeout", "300", "postgres", "redis")
        run("run", "--rm", "--no-deps", "migrate")
        run(
            "run",
            "--rm",
            "--no-deps",
            "backend",
            "python",
            "-m",
            "app.commands.sync_release_notes",
            "--check-only",
        )
        run(
            "up",
            "-d",
            "--no-deps",
            "--wait",
            "--wait-timeout",
            "300",
            *APPLICATION_SERVICES,
        )
    run(
        "exec",
        "-T",
        "backend",
        "python",
        "-m",
        "app.commands.sync_release_notes",
        "--origin",
        origin,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version")
    parser.add_argument(
        "--previous", help="Last successfully deployed Git ref; must be an ancestor of HEAD"
    )
    parser.add_argument("--origin", help="Production HTTPS origin")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--backup-confirmed", action="store_true")
    parser.add_argument(
        "--bootstrap-baseline",
        action="store_true",
        help="Explicit baseline for legacy deployments without identity",
    )
    parser.add_argument(
        "--sync-only",
        action="store_true",
        help="Recheck running deployment and retry draft registration without rebuilding",
    )
    args = parser.parse_args()
    try:
        if args.sync_only and not args.apply:
            raise ValueError("--sync-only 需要 --apply；它会写入部署草稿")
        if not args.sync_only and (not args.version or not args.previous):
            raise ValueError("需要 --version 和 --previous")
        manifest = {} if args.sync_only else prepare(args.version, args.previous)
        if args.apply:
            if not args.origin:
                raise ValueError("执行时必须指定 --origin")
            execute(args, manifest)
        else:
            print(json.dumps(manifest, ensure_ascii=False, indent=2))
            print("仅预览，未构建、部署或写入数据库。", file=sys.stderr)
    except (ValueError, subprocess.CalledProcessError, urllib.error.URLError) as exc:
        print(
            str(exc)
            if isinstance(exc, ValueError)
            else "发布步骤失败，已停止；未自动回滚或发布公告。",
            file=sys.stderr,
        )
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
