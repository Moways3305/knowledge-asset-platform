export const ADMIN_OVERVIEW_INVALIDATED_EVENT = "kap:admin-overview-invalidated";

const ADMIN_OVERVIEW_AFFECTING_PREFIXES = ["/api/v1/admin/", "/admin/ops/"];
const PROJECT_MEMBERSHIP_PATH = /^\/api\/v1\/projects\/[^/?#]+\/members(?:\/[^/?#]+)?(?:[?#]|$)/;

export function affectsAdminOverview(path: string): boolean {
  return (
    ADMIN_OVERVIEW_AFFECTING_PREFIXES.some((prefix) => path.startsWith(prefix)) ||
    PROJECT_MEMBERSHIP_PATH.test(path)
  );
}

export function invalidateAdminOverview(path: string): void {
  if (!affectsAdminOverview(path) || typeof window === "undefined") return;
  window.dispatchEvent(new CustomEvent(ADMIN_OVERVIEW_INVALIDATED_EVENT, { detail: { path } }));
}
