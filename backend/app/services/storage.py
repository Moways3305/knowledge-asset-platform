"""文件存储抽象与本地文件系统后端。

边界与安全：
- 上传的文件字节写入**受控服务端存储**；返回的存储引用（storage ref）是
  **server-only 内部标识**，**绝不进入任何 API 响应 schema**（沿用存储与审计脱敏口径）。
- 存储引用统一以 `internal://` 前缀表达（既是内部标识，又被审计值级脱敏标记覆盖，
  作为纵深防御）；本地后端把 `internal://<key>` 映射到 `<storage_root>/<key>`。
- 文件名归一化：用户提供的文件名只取 basename 并清洗为安全字符集，**绝不让其成为
  路径穿越输入**；实际存储 key 另含随机段，避免碰撞与可猜测。
- 大小限制：单文件上限 `MAX_UPLOAD_BYTES`，超限由调用方返回 413。

当前实现 local 后端；S3/OSS 等对象存储后端可在保持接口一致的前提下替换。
"""

from __future__ import annotations

import os
import re
import uuid
from pathlib import Path

from app.core.config import get_settings

# 单文件上限（25 MiB）。最小闭环用常量；生产可改为配置。
MAX_UPLOAD_BYTES = 25 * 1024 * 1024

# 内部存储引用前缀（server-only，绝不外泄）。
_REF_PREFIX = "internal://"

_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]")


class StorageError(Exception):
    """存储层错误（路径非法 / 引用不合法等）。"""


def _contains(root: Path, candidate: Path) -> bool:
    """判断 candidate 是否真正位于 root 之内（真实路径包含，而非字符串前缀）。

    用 `relative_to` 做祖先关系判断，避免 `/a/root` 与 `/a/root2` 这类共享前缀的
    兄弟目录被字符串 startswith 误判为包含（路径穿越 / 兄弟前缀绕过）。
    """
    try:
        candidate.resolve().relative_to(root)
        return True
    except ValueError:
        return False


def safe_filename(name: str | None) -> str:
    """把用户提供的文件名归一化为安全的 basename。

    - 先取 basename（去掉任何目录分量，含 `\\` / `/`），杜绝路径穿越。
    - 仅保留字母数字与 `._-`，其余替换为 `_`；去掉首尾 `.`/`_`。
    - 空 / 全非法 → 回退 `file`；长度截断到 120。
    """
    raw = (name or "").replace("\\", "/")
    base = os.path.basename(raw)
    cleaned = _SAFE_NAME_RE.sub("_", base).strip("._")
    return (cleaned or "file")[:120]


class LocalFileStorage:
    """本地文件系统存储后端（dev/test）。"""

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root).resolve()

    @property
    def root(self) -> Path:
        return self._root

    def save(self, content: bytes, *, original_name: str | None) -> str:
        """写入文件字节，返回 server-only 内部存储引用（`internal://<key>`）。

        key = `<uuid4hex>/<safe_name>`；随机段避免碰撞且不可由文件名反推路径。
        """
        if len(content) > MAX_UPLOAD_BYTES:
            raise StorageError("file_too_large")
        key = f"{uuid.uuid4().hex}/{safe_filename(original_name)}"
        path = self._root / key
        # 归属校验：解析后必须真正位于 root 之内（真实路径包含，防穿越 / 兄弟前缀）。
        if not _contains(self._root, path):
            raise StorageError("invalid_storage_path")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return f"{_REF_PREFIX}{key}"

    def resolve_path(self, ref: str) -> Path:
        """把内部存储引用解析回本地路径（server-only，仅供后端读取，不外泄）。"""
        if not ref.startswith(_REF_PREFIX):
            raise StorageError("invalid_storage_ref")
        key = ref[len(_REF_PREFIX) :]
        path = (self._root / key).resolve()
        if not _contains(self._root, path):
            raise StorageError("invalid_storage_path")
        return path

    def exists(self, ref: str) -> bool:
        try:
            return self.resolve_path(ref).is_file()
        except StorageError:
            return False


def get_storage() -> LocalFileStorage:
    """FastAPI 依赖：返回按配置 root 初始化的本地存储后端。

    测试经 `app.dependency_overrides[get_storage]` 覆盖到临时目录，保持 hermetic。
    """
    return LocalFileStorage(get_settings().storage_root)
