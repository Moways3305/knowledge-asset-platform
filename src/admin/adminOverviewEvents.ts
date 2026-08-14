export const ADMIN_OVERVIEW_INVALIDATED_EVENT = "kap:admin-overview-invalidated";

const ADMIN_OVERVIEW_AFFECTING_PREFIXES = ["/api/v1/admin/", "/admin/ops/"];

export function affectsAdminOverview(path: string): boolean {
  return ADMIN_OVERVIEW_AFFECTING_PREFIXES.some((prefix) => path.startsWith(prefix));
}

export function invalidateAdminOverview(path: string): void {
  if (!affectsAdminOverview(path) || typeof window === "undefined") return;
  window.dispatchEvent(new CustomEvent(ADMIN_OVERVIEW_INVALIDATED_EVENT, { detail: { path } }));
}
