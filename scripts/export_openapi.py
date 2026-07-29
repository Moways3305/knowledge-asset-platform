#!/usr/bin/env python3
"""导出 FastAPI OpenAPI spec 到 docs/api/openapi.json（版本化的 API 契约）。

只读取代码定义的 schema：调用 `create_app().openapi()`，**不连接数据库、不读取 .env、
不发起任何网络请求**（FastAPI 的 openapi() 纯由路由 / Pydantic 模型生成）。

两道保障：
  1. stable sort —— `json.dumps(sort_keys=True, indent=2)`，键序稳定，避免非实质
     变更（dict 顺序抖动）导致 CI diff 误报。
  2. no-leak 扫描 —— server-only 内部标识 / 密钥不得经**响应**契约外泄。

no-leak 的扫描范围是经过设计的（避免 false positive / false negative）：
  - 只扫**响应可达**的 schema：从每个 operation 的 `responses.*.content.*.schema` 出发，
    沿 `$ref` / properties / items / allOf 等传递闭包收集组件。请求体（如管理员注册外部
    Agent 时**主动填入**的 `api_key` / `external_workflow_id`）是合法输入、不算外泄，
    故不在扫描范围内。
  - 只看**结构标识**：property 名、example / default / const / enum 值；**不扫**
    description / summary / title 等自由文本——这些 docstring 常会**描述**安全红线
    （“绝不暴露 storage_ref”之类），属正当文档，不应误报。
  - 命中即报错退出且不写盘。

用法：
  python scripts/export_openapi.py            # 导出并校验
  python scripts/export_openapi.py --check    # 只校验现有 openapi.json 与最新 spec 是否一致（不写盘）

CI 用前者 + `git diff --exit-code docs/api/openapi.json` 检测 spec 漂移。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# 仓库根与后端目录（基于脚本位置，使任意 cwd 下行为一致）。
REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = REPO_ROOT / "backend"
OUTPUT_PATH = REPO_ROOT / "docs" / "api" / "openapi.json"

# 安全红线：响应契约里绝不应出现的 server-only 内部标识 / 密钥 / 凭证字段名
# （大小写不敏感，按子串匹配，故 `external_workflow_id` 含 `workflow_id`、
# `weknora_kb_id` 含 `kb_id`）。
FORBIDDEN_TOKENS = (
    "weknora_kb_id",
    "weknora_doc_id",
    "kb_id",
    "dataset_id",
    "workflow_id",
    "api_key",
    "app_secret",
    "jwt_secret",
    "token_hash",
    "password_hash",
    "model_ref_secret",
    "hash_secret",
    "storage_ref",
    "source_file_ref",
    "download_url",
    "bucket",
)


def build_spec() -> dict[str, Any]:
    """生成 OpenAPI dict（延迟把后端加入 sys.path，使脚本对 cwd 不敏感）。"""
    sys.path.insert(0, str(BACKEND_DIR))
    from app.main import create_app  # noqa: E402  (路径注入后才可导入)

    return create_app().openapi()


def serialize(spec: dict[str, Any]) -> str:
    """稳定排序 + 保留中文 + 末尾换行（利于 diff / POSIX 文本规范）。"""
    return json.dumps(spec, sort_keys=True, indent=2, ensure_ascii=False) + "\n"


def _iter_component_refs(node: Any):
    """产出 node 内所有 `#/components/schemas/X` 的 X 名称。"""
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/components/schemas/"):
            yield ref.rsplit("/", 1)[-1]
        for value in node.values():
            yield from _iter_component_refs(value)
    elif isinstance(node, list):
        for item in node:
            yield from _iter_component_refs(item)


def _response_schema_nodes(spec: dict[str, Any]) -> list[Any]:
    """收集所有 operation 响应里的 schema 节点（内联或 $ref）。"""
    nodes: list[Any] = []
    for path_item in spec.get("paths", {}).values():
        if not isinstance(path_item, dict):
            continue
        for operation in path_item.values():
            if not isinstance(operation, dict):
                continue
            for response in operation.get("responses", {}).values():
                for media in (response.get("content") or {}).values():
                    schema = media.get("schema")
                    if schema is not None:
                        nodes.append(schema)
    return nodes


def _response_reachable_components(spec: dict[str, Any]) -> set[str]:
    """从响应 schema 出发，沿 $ref 取传递闭包，返回响应可达的组件名集合。"""
    components = spec.get("components", {}).get("schemas", {})
    frontier = [
        name for node in _response_schema_nodes(spec) for name in _iter_component_refs(node)
    ]
    reachable: set[str] = set()
    while frontier:
        name = frontier.pop()
        if name in reachable:
            continue
        reachable.add(name)
        frontier.extend(_iter_component_refs(components.get(name, {})))
    return reachable


def _collect_identifiers(node: Any, out: set[str]) -> None:
    """收集 property 名与 example/default/const/enum 值；不收 description 等自由文本。"""
    if isinstance(node, dict):
        props = node.get("properties")
        if isinstance(props, dict):
            out.update(props.keys())
        for key in ("example", "default", "const"):
            value = node.get(key)
            if isinstance(value, str):
                out.add(value)
        enum = node.get("enum")
        if isinstance(enum, list):
            out.update(str(x) for x in enum if isinstance(x, (str, int)))
        for value in node.values():
            _collect_identifiers(value, out)
    elif isinstance(node, list):
        for item in node:
            _collect_identifiers(item, out)


def scan_for_leaks(spec: dict[str, Any]) -> list[str]:
    """返回响应契约中命中的红线 token（大小写不敏感）。空列表＝无外泄。"""
    components = spec.get("components", {}).get("schemas", {})
    identifiers: set[str] = set()
    for name in _response_reachable_components(spec):
        _collect_identifiers(components.get(name, {}), identifiers)
    for node in _response_schema_nodes(spec):
        _collect_identifiers(node, identifiers)
    # 用空格连接，避免红线 token 跨标识边界产生假匹配。
    haystack = " ".join(identifiers).lower()
    return [token for token in FORBIDDEN_TOKENS if token in haystack]


def main() -> int:
    parser = argparse.ArgumentParser(description="Export & validate the OpenAPI contract.")
    parser.add_argument(
        "--check",
        action="store_true",
        help="只比对现有 openapi.json 与最新 spec 是否一致，不写盘（不一致则退出码 1）。",
    )
    args = parser.parse_args()

    spec = build_spec()

    leaks = scan_for_leaks(spec)
    if leaks:
        print(
            "no-leak 校验失败：响应契约中出现安全红线字段名：" + ", ".join(leaks),
            file=sys.stderr,
        )
        print(
            "已中止，不写盘。请修正对应响应 schema（server-only 标识不得进入响应模型）。",
            file=sys.stderr,
        )
        return 1

    text = serialize(spec)

    if args.check:
        if not OUTPUT_PATH.exists():
            print(
                f"{OUTPUT_PATH} 不存在；请先运行 `python scripts/export_openapi.py` 生成。",
                file=sys.stderr,
            )
            return 1
        if OUTPUT_PATH.read_text(encoding="utf-8") != text:
            print(
                "OpenAPI 契约漂移：docs/api/openapi.json 与代码定义的 spec 不一致。\n"
                "请运行 `python scripts/export_openapi.py` 重新生成并提交。",
                file=sys.stderr,
            )
            return 1
        print("OpenAPI 契约校验通过：与代码定义一致。")
        return 0

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    # newline="\n"：强制 LF，避免 Windows 下写出 CRLF 而 CI(Linux) 重生成为 LF 导致 diff 误报。
    OUTPUT_PATH.write_text(text, encoding="utf-8", newline="\n")
    path_count = len(spec.get("paths", {}))
    print(
        f"已导出 OpenAPI 契约 → {OUTPUT_PATH.relative_to(REPO_ROOT)}"
        f"（{path_count} 个路径；no-leak 扫描 {len(FORBIDDEN_TOKENS)} 项全部通过）。"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
