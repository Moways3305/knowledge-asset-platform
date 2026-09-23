"""Run inside the deployed backend after Compose health checks; never publishes."""

import argparse
import asyncio
import sys
from urllib.parse import urlsplit

import httpx

from app.core.release_manifest import load_manifest
from app.db.session import get_sessionmaker
from app.services.release_deployment import (
    check_release_identity,
    record_deployment,
    verify_deployment,
)


async def run(origin: str, check_only: bool = False) -> None:
    manifest = load_manifest()
    if manifest is None:
        raise ValueError("镜像未包含发布清单，不能登记部署")
    if check_only:
        async with get_sessionmaker()() as session:
            await check_release_identity(session, manifest)
        print("发布身份预检通过，未登记部署或创建草稿")
        return
    parsed = urlsplit(origin)
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.username
        or parsed.password
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("必须使用生产用户入口的 HTTPS origin（不含路径、凭证或查询参数）")
    async with httpx.AsyncClient(base_url=origin, timeout=20, follow_redirects=False) as client:
        await verify_deployment(client, manifest)
    async with get_sessionmaker()() as session:
        note = await record_deployment(session, manifest)
        print(
            f"部署已验证：{note.version}；日志{'已发布，保持不变' if note.published_at else '待管理员审核'}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--origin", default="")
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    try:
        asyncio.run(run(args.origin, args.check_only))
    except (ValueError, httpx.HTTPError) as exc:
        # Do not print request URLs, credentials or configuration bodies.
        print(
            str(exc) if isinstance(exc, ValueError) else "发布入口探测失败；未登记部署",
            file=sys.stderr,
        )
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
