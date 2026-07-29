"""WorkBuddy Connector 共享安装产物清单与受权下载。

清单是部署产物，不含任何用户数据。服务端每次读取时校验路径、目标集合、sha256 和
发布渠道状态；生产正式版缺少签名/公证、内部版未显式启用或文件哈希不符时 fail closed。
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from app.core.config import get_settings
from app.core.errors import denied
from app.schemas.permission import CallerContext
from app.schemas.workbuddy import (
    WorkbuddyArchitecture,
    WorkbuddyConnectorArtifactOut,
    WorkbuddyConnectorManifestOut,
    WorkbuddyPlatform,
)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_VERSION_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?$")
_REQUIRED_TARGETS = {("windows", "x64"), ("macos", "arm64"), ("macos", "x64")}


@dataclass(frozen=True)
class ResolvedArtifact:
    descriptor: WorkbuddyConnectorArtifactOut
    path: Path


def _require_business(caller: CallerContext) -> None:
    if not caller.is_active or not caller.is_business_user:
        raise denied(403, "workbuddy_not_business_user", "仅在职业务用户可下载 WorkBuddy 连接器")


def _safe_root() -> Path:
    return Path(get_settings().workbuddy_connector_artifact_root).resolve()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_manifest(caller: CallerContext) -> list[ResolvedArtifact]:
    _require_business(caller)
    settings = get_settings()
    root = _safe_root()
    manifest_name = Path(settings.workbuddy_connector_manifest)
    if manifest_name.name != str(manifest_name):
        raise denied(503, "workbuddy_connector_unavailable", "连接器下载暂不可用")
    try:
        raw = json.loads((root / manifest_name).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        raise denied(503, "workbuddy_connector_unavailable", "连接器下载暂不可用") from None
    if not isinstance(raw, dict):
        raise denied(503, "workbuddy_connector_unavailable", "连接器下载暂不可用")

    version = raw.get("version")
    channel = raw.get("channel")
    items = raw.get("artifacts")
    if not isinstance(version, str) or not _VERSION_RE.fullmatch(version):
        raise denied(503, "workbuddy_connector_unavailable", "连接器下载暂不可用")
    if channel not in {"production", "internal"} or not isinstance(items, list):
        raise denied(503, "workbuddy_connector_unavailable", "连接器下载暂不可用")
    if channel == "internal" and not settings.workbuddy_connector_allow_internal:
        raise denied(
            503,
            "workbuddy_connector_internal_disabled",
            "企业内部版连接器暂不可用",
        )

    targets: set[tuple[str, str]] = set()
    expected_entries = {str(manifest_name)}
    resolved: list[ResolvedArtifact] = []
    for item in items:
        if not isinstance(item, dict):
            raise denied(503, "workbuddy_connector_unavailable", "连接器下载暂不可用")
        platform = item.get("platform")
        architecture = item.get("architecture")
        filename = item.get("filename")
        sha256 = item.get("sha256")
        signed = item.get("signed") is True
        notarized = item.get("notarized") is True
        target = (platform, architecture)
        if target not in _REQUIRED_TARGETS or target in targets:
            raise denied(503, "workbuddy_connector_unavailable", "连接器下载暂不可用")
        platform = cast(WorkbuddyPlatform, platform)
        architecture = cast(WorkbuddyArchitecture, architecture)
        if not isinstance(filename, str) or Path(filename).name != filename:
            raise denied(503, "workbuddy_connector_unavailable", "连接器下载暂不可用")
        expected_entries.add(filename)
        if not isinstance(sha256, str) or not _SHA256_RE.fullmatch(sha256):
            raise denied(503, "workbuddy_connector_unavailable", "连接器下载暂不可用")
        if channel == "production":
            if platform == "macos" and (not signed or not notarized):
                raise denied(503, "workbuddy_connector_unsigned", "正式连接器尚未完成签名发布")
            if platform == "windows" and not signed:
                raise denied(503, "workbuddy_connector_unsigned", "正式连接器尚未完成签名发布")
        elif item.get("signed") is not False or item.get("notarized") is not False:
            raise denied(503, "workbuddy_connector_unavailable", "连接器下载暂不可用")
        path = (root / filename).resolve()
        if root not in path.parents or not path.is_file():
            raise denied(503, "workbuddy_connector_unavailable", "连接器下载暂不可用")
        digest = _sha256_file(path)
        if digest != sha256:
            raise denied(503, "workbuddy_connector_integrity_failed", "连接器完整性校验失败")
        targets.add(target)
        resolved.append(
            ResolvedArtifact(
                descriptor=WorkbuddyConnectorArtifactOut(
                    platform=platform,
                    architecture=architecture,
                    version=version,
                    filename=filename,
                    sha256=sha256,
                    download_path=(
                        f"/api/v1/auth/workbuddy-connectors/{platform}/{architecture}/download"
                    ),
                    release_status=channel,
                    signed=signed,
                    notarized=notarized,
                ),
                path=path,
            )
        )
    if targets != _REQUIRED_TARGETS:
        raise denied(503, "workbuddy_connector_unavailable", "连接器下载暂不可用")
    try:
        actual_entries = {path.name for path in root.iterdir()}
    except OSError:
        raise denied(503, "workbuddy_connector_unavailable", "连接器下载暂不可用") from None
    if actual_entries != expected_entries:
        raise denied(503, "workbuddy_connector_unavailable", "连接器下载暂不可用")
    return resolved


def get_manifest(caller: CallerContext) -> WorkbuddyConnectorManifestOut:
    artifacts = _read_manifest(caller)
    return WorkbuddyConnectorManifestOut(
        version=artifacts[0].descriptor.version,
        artifacts=[item.descriptor for item in artifacts],
    )


def resolve_download(caller: CallerContext, platform: str, architecture: str) -> ResolvedArtifact:
    for item in _read_manifest(caller):
        if item.descriptor.platform == platform and item.descriptor.architecture == architecture:
            return item
    # 支持集合外和不存在的目标统一 404，避免枚举部署细节。
    raise denied(404, "workbuddy_connector_not_found", "未找到该平台连接器")
