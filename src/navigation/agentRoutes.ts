export const AI_WORKSPACE_PATH = "/ai-workspace";
export const MAINTENANCE_AGENT_PATH = "/ai-workspace/agents/knowledge-maintenance";
export const MAINTENANCE_AGENT_KEY = "knowledge-maintenance";

export function agentConversationHref(
  agentKey: string,
  sessionId?: string | null,
  library?: string | null,
) {
  const params = new URLSearchParams({ agent: agentKey });
  if (sessionId) params.set("session", sessionId);
  else if (library) params.set("library", library);
  return `${AI_WORKSPACE_PATH}?${params}`;
}

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
