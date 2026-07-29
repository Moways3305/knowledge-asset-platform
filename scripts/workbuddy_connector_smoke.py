"""Safe post-deploy WorkBuddy Connector manifest/download smoke.

Session values are read from environment variables and are never printed. Only endpoint status,
target and checksum-match booleans are emitted.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request

_MANIFEST_PATH = "/api/v1/auth/workbuddy-connectors"
_DOWNLOAD_PATH = re.compile(
    r"^/api/v1/auth/workbuddy-connectors/(windows|macos)/(x64|arm64)/download$"
)


def _request(base_url: str, path: str, *, session_cookie: str | None):
    headers = {}
    if session_cookie:
        headers["Cookie"] = f"kap_session={session_cookie}"
    return urllib.request.urlopen(
        urllib.request.Request(
            urllib.parse.urljoin(base_url.rstrip("/") + "/", path), headers=headers
        ),
        timeout=30,
    )


def _status(base_url: str, path: str, *, session_cookie: str | None) -> int:
    try:
        with _request(base_url, path, session_cookie=session_cookie) as response:
            return response.status
    except urllib.error.HTTPError as exc:
        return exc.code


def run_smoke(
    base_url: str,
    *,
    session_cookie: str,
    unauthorized_session_cookie: str,
    platform: str,
    architecture: str,
    expected_channel: str = "production",
) -> dict:
    unauthenticated_status = _status(base_url, _MANIFEST_PATH, session_cookie=None)
    if unauthenticated_status not in {401, 403}:
        raise RuntimeError("unauthenticated connector manifest request was not rejected")
    unauthorized_user_status = _status(
        base_url,
        _MANIFEST_PATH,
        session_cookie=unauthorized_session_cookie,
    )
    if unauthorized_user_status != 403:
        raise RuntimeError("non-business connector manifest request was not forbidden")

    with _request(base_url, _MANIFEST_PATH, session_cookie=session_cookie) as response:
        if response.status != 200:
            raise RuntimeError("authenticated connector manifest request failed")
        manifest = json.load(response)
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list) or len(artifacts) != 3:
        raise RuntimeError("connector manifest is incomplete")
    if any(item.get("release_status") != expected_channel for item in artifacts):
        raise RuntimeError("unexpected connector release channel was returned")
    if expected_channel == "internal" and any(
        item.get("signed") is not False or item.get("notarized") is not False for item in artifacts
    ):
        raise RuntimeError("internal connector artifact claimed a release signature")
    artifact = next(
        (
            item
            for item in artifacts
            if item.get("platform") == platform and item.get("architecture") == architecture
        ),
        None,
    )
    if artifact is None:
        raise RuntimeError("requested connector target is absent")
    download_path = artifact.get("download_path")
    expected = artifact.get("sha256")
    if not isinstance(download_path, str) or not _DOWNLOAD_PATH.fullmatch(download_path):
        raise RuntimeError("connector download path is invalid")
    if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise RuntimeError("connector checksum is invalid")

    digest = hashlib.sha256()
    with _request(base_url, download_path, session_cookie=session_cookie) as response:
        if response.status != 200:
            raise RuntimeError("connector download failed")
        for chunk in iter(lambda: response.read(1024 * 1024), b""):
            digest.update(chunk)
    checksum_matches = digest.hexdigest() == expected
    if not checksum_matches:
        raise RuntimeError("downloaded connector checksum mismatch")
    return {
        "manifest_status": 200,
        "unauthenticated_status": unauthenticated_status,
        "unauthorized_user_status": unauthorized_user_status,
        "target": f"{platform}-{architecture}",
        "release_status": expected_channel,
        "download_status": 200,
        "checksum_matches": checksum_matches,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--platform", choices=("windows", "macos"), default="windows")
    parser.add_argument("--architecture", choices=("x64", "arm64"), default="x64")
    parser.add_argument(
        "--expected-channel",
        choices=("production", "internal"),
        default="production",
    )
    parser.add_argument("--session-cookie-env", default="KAP_SMOKE_SESSION_COOKIE")
    parser.add_argument(
        "--unauthorized-session-cookie-env",
        default="KAP_SMOKE_UNAUTHORIZED_SESSION_COOKIE",
    )
    args = parser.parse_args()
    session_cookie = os.environ.get(args.session_cookie_env, "")
    if not session_cookie:
        raise SystemExit(
            f"missing business-user session in environment variable {args.session_cookie_env}"
        )
    unauthorized_session_cookie = os.environ.get(args.unauthorized_session_cookie_env, "")
    if not unauthorized_session_cookie:
        raise SystemExit(
            "missing non-business session in environment variable "
            f"{args.unauthorized_session_cookie_env}"
        )
    print(
        json.dumps(
            run_smoke(
                args.base_url,
                session_cookie=session_cookie,
                unauthorized_session_cookie=unauthorized_session_cookie,
                platform=args.platform,
                architecture=args.architecture,
                expected_channel=args.expected_channel,
            ),
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
