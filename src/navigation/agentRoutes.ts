export const AI_WORKSPACE_PATH = "/ai-workspace";
export const MAINTENANCE_AGENT_PATH = "/ai-workspace/agents/knowledge-maintenance";

/** Old notifications/bookmarks retain their library, reminder, filters and fragment. */
export function legacyMaintenanceAgentDestination(search: string, hash = "") {
  return `${MAINTENANCE_AGENT_PATH}${search}${hash}`;
}

/** Business tabs change their own query fields without losing the workspace session. */
export function maintenanceAgentHref(
  search: string,
  changes: Record<string, string | null> = {},
  hash = "",
) {
  const params = new URLSearchParams(search);
  for (const [name, value] of Object.entries(changes)) {
    if (value === null) params.delete(name);
    else params.set(name, value);
  }
  const query = params.toString();
  return `${MAINTENANCE_AGENT_PATH}${query ? `?${query}` : ""}${hash}`;
}
