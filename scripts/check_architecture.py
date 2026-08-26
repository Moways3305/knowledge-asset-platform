"""Executable dependency boundaries for backend and upload frontend."""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVICES = ROOT / "backend" / "app" / "services"
API = ROOT / "backend" / "app" / "api"

GOVERNED_API_FILES = {
    "agent_gateway.py",
    "ingest.py",
    "review.py",
    "original_access.py",
    "notifications.py",
}
# All API modules are scanned. These six pre-existing infrastructure/configuration
# baselines are bounded by operation count so they cannot grow silently. Owner:
# platform architecture; removal deadline: 2026-12-31. A reduction is always allowed.
LEGACY_API_ORM_BASELINE = {
    "auth.py": {"commit": 13},
    "generation_models.py": {"commit": 5},
    "knowledge.py": {"execute": 1},
    "model_connections.py": {"commit": 5},
    "ops.py": {"commit": 1, "execute": 12},
    "weknora_admin.py": {"commit": 6},
}
FORBIDDEN_NOTIFICATION_PRODUCERS = {
    "ingest",
    "ingest_confirmation",
    "ingest_persistence",
    "knowledge",
    "my_knowledge",
    "original_access",
    "review",
}
NOTIFICATION_IMPORT_ALLOWED = {"notifications.py", "notification_event_consumers.py"}
NOTIFICATION_WRITE_ALLOWED = {"alert.py", "notification_event_consumers.py"}
FORBIDDEN_NOTIFICATION_IMPORTS = {
    "review",
    "ingest",
    "ingest_confirmation",
    "ingest_status",
    "original_access",
    "knowledge",
}
FORBIDDEN_DIRECT_EDGES = {
    ("review", "ingest"),
    ("ingest_confirmation", "review"),
}
FORBIDDEN_API_SESSION_WRITES = {"add", "add_all", "delete", "commit", "flush", "execute"}
SERVICE_FACADE_MAX_LINES = {
    "review.py": 100,
    "upload_sessions.py": 100,
    "knowledge.py": 100,
}
PENDING_BATCH_MAX_LINES = 400


def _service_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            prefix = "app.services."
            if node.module.startswith(prefix):
                module = node.module[len(prefix) :]
                imports.add(module)
                imports.update(f"{module}.{alias.name}" for alias in node.names)
            elif node.module == "app.services":
                imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                prefix = "app.services."
                if alias.name.startswith(prefix):
                    imports.add(alias.name[len(prefix) :])
    return imports


def _service_module_name(path: Path, services_root: Path = SERVICES) -> str:
    relative = path.relative_to(services_root).with_suffix("")
    parts = relative.parts
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _service_graph(services_root: Path = SERVICES) -> dict[str, set[str]]:
    paths = sorted(services_root.rglob("*.py"))
    modules = {name for path in paths if (name := _service_module_name(path, services_root))}
    return {
        _service_module_name(path, services_root): _service_imports(path) & modules
        for path in paths
        if _service_module_name(path, services_root)
    }


def _cycles(graph: dict[str, set[str]]) -> list[list[str]]:
    found: set[tuple[str, ...]] = set()

    def visit(node: str, path: list[str]) -> None:
        if node in path:
            cycle = path[path.index(node) :] + [node]
            rotations = [
                tuple(cycle[index:-1] + cycle[:index] + [cycle[index]])
                for index in range(len(cycle) - 1)
            ]
            found.add(min(rotations))
            return
        if len(path) > len(graph):
            return
        for target in graph.get(node, set()):
            if target in graph:
                visit(target, [*path, node])

    for name in graph:
        visit(name, [])
    return [list(cycle) for cycle in sorted(found)]


def _api_session_writes(path: Path) -> list[tuple[int, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    violations = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        owner = node.func.value
        if (
            isinstance(owner, ast.Name)
            and owner.id == "session"
            and node.func.attr in FORBIDDEN_API_SESSION_WRITES
        ):
            violations.append((node.lineno, node.func.attr))
    return violations


def _direct_notification_writes(path: Path) -> list[tuple[int, str]]:
    """Find local-notification writes outside the dedicated consumer/writer."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    violations: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Attribute) and node.func.attr == "record_local_notification":
            violations.append((node.lineno, "record_local_notification"))
        elif isinstance(node.func, ast.Name) and node.func.id == "NotificationRecord":
            violations.append((node.lineno, "NotificationRecord"))
    return violations


def main() -> int:
    failures: list[str] = []
    graph = _service_graph()
    for source, target in FORBIDDEN_DIRECT_EDGES:
        if target in graph.get(source, set()):
            failures.append(f"forbidden service edge: {source} -> {target}")
    notification_edges = graph.get("notifications", set()) & FORBIDDEN_NOTIFICATION_IMPORTS
    for target in sorted(notification_edges):
        failures.append(f"notification command boundary reversed: notifications -> {target}")
    for producer in sorted(FORBIDDEN_NOTIFICATION_PRODUCERS):
        if "notifications" in graph.get(producer, set()):
            failures.append(f"notification outbox bypass: {producer} -> notifications")
    for path in sorted(SERVICES.rglob("*.py")):
        if path.name in NOTIFICATION_IMPORT_ALLOWED:
            continue
        if "notifications" in _service_imports(path):
            relative = path.relative_to(SERVICES).as_posix()
            failures.append(f"notification outbox bypass: services/{relative} -> notifications")
    for path in sorted(SERVICES.rglob("*.py")):
        if path.name in NOTIFICATION_WRITE_ALLOWED:
            continue
        relative = path.relative_to(SERVICES).as_posix()
        for line, operation in _direct_notification_writes(path):
            failures.append(
                f"notification record outbox bypass: services/{relative}:{line} calls {operation}"
            )

    for cycle in _cycles(graph):
        failures.append("service cycle: " + " -> ".join(cycle))

    for file_name, maximum in SERVICE_FACADE_MAX_LINES.items():
        path = SERVICES / file_name
        line_count = len(path.read_text(encoding="utf-8").splitlines())
        if line_count > maximum:
            failures.append(
                f"service facade grew: app/services/{file_name} lines {line_count} > {maximum}"
            )
        for line, operation in _api_session_writes(path):
            failures.append(
                f"service facade ORM boundary: app/services/{file_name}:{line} "
                f"calls session.{operation}()"
            )

    api_paths = sorted(API.glob("*.py"))
    for path in api_paths:
        violations = _api_session_writes(path)
        baseline = LEGACY_API_ORM_BASELINE.get(path.name, {})
        counts: dict[str, int] = {}
        for line, operation in violations:
            counts[operation] = counts.get(operation, 0) + 1
            if operation not in baseline:
                failures.append(
                    f"API ORM boundary: app/api/{path.name}:{line} calls session.{operation}()"
                )
        for operation, count in counts.items():
            maximum = baseline.get(operation)
            if maximum is not None and count > maximum:
                failures.append(
                    f"API ORM legacy baseline grew: app/api/{path.name} "
                    f"session.{operation}() count {count} > {maximum}"
                )

    upload_pages = ROOT / "src" / "pages" / "upload"
    for page in upload_pages.glob("*.tsx"):
        if page.name.endswith(".test.tsx"):
            continue
        source = page.read_text(encoding="utf-8")
        if 'from "../../api/' in source or "from '../../api/" in source:
            failures.append(
                f"frontend API boundary: {page.name} imports transport API; use a hook/command"
            )

    pending = (upload_pages / "PendingBatchActions.tsx").read_text(encoding="utf-8")
    pending_line_count = len(pending.splitlines())
    if pending_line_count > PENDING_BATCH_MAX_LINES:
        failures.append(
            "frontend orchestration boundary: PendingBatchActions.tsx lines "
            f"{pending_line_count} > {PENDING_BATCH_MAX_LINES}"
        )
    for boundary in (
        "PendingBatchActionBar",
        "PendingBatchAiReviewDrawer",
        "PendingBatchDecisionDialogs",
        "PendingBatchNamingReview",
        "PendingBatchTargetReview",
        "usePendingBatchReviewController",
    ):
        if boundary not in pending:
            failures.append(
                f"frontend structure boundary: PendingBatchActions.tsx bypasses {boundary}"
            )

    controller = (upload_pages / "usePendingBatchReviewController.ts").read_text(encoding="utf-8")
    for boundary in (
        "usePendingBatchAiReview",
        "usePendingBatchTargetOptions",
        "pendingBatchCommands",
        "pendingBatchReviewState",
    ):
        if boundary not in controller:
            failures.append(
                "frontend controller boundary: "
                f"usePendingBatchReviewController.ts bypasses {boundary}"
            )

    if failures:
        print("Architecture boundary violations:", file=sys.stderr)
        for failure in failures:
            print(f" - {failure}", file=sys.stderr)
        return 1
    print(
        "Architecture boundaries passed: "
        f"all {len(graph)} service modules in recursive graph acyclic, "
        f"all {len(api_paths)} API modules scanned, "
        f"{len(GOVERNED_API_FILES)} governed APIs command-free, "
        f"{len(LEGACY_API_ORM_BASELINE)} bounded legacy API baselines, "
        "3 service facades ORM-free and size-bounded, "
        "all service notification imports and record writes use Outbox, "
        f"upload orchestrator size-bounded at {PENDING_BATCH_MAX_LINES} lines"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
