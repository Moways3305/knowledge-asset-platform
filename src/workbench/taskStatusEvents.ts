export const TASK_STATUS_INVALIDATED_EVENT = "kap:task-status-invalidated";

const TASK_AFFECTING_PATHS = [
  "/api/v1/ingest/",
  "/api/v1/reviews/",
  "/api/v1/review/",
  "/api/v1/original-access/",
  "/admin/ops/indexing/",
  "/api/v1/admin/ops/indexing/",
  "/api/v1/admin/weknora/",
];

export function affectsTaskStatus(path: string): boolean {
  return (
    TASK_AFFECTING_PATHS.some((prefix) => path.startsWith(prefix)) ||
    path.includes("/original-access/") ||
    path.endsWith("/retry-index") ||
    path.endsWith("/upgrade-company") ||
    path.endsWith("/confirm-asset")
  );
}

export function invalidateTaskStatus(path: string): void {
  if (!affectsTaskStatus(path) || typeof window === "undefined") return;
  window.dispatchEvent(new CustomEvent(TASK_STATUS_INVALIDATED_EVENT, { detail: { path } }));
}
