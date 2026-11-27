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

/** Focused panels stay alongside the conversation, preserving reminder scope. */
export function maintenancePanelHref(
  search: string,
  changes: Record<string, string | null> = {},
  hash = "",
) {
  const params = new URLSearchParams(search);
  params.set("agent", MAINTENANCE_AGENT_KEY);
  if (params.has("tab") && !params.has("panel")) params.set("panel", params.get("tab")!);
  params.delete("tab");
  for (const [name, value] of Object.entries(changes)) {
    const field = name === "tab" ? "panel" : name;
    if (value === null) params.delete(field);
    else params.set(field, value);
  }
  const query = params.toString();
  return `${AI_WORKSPACE_PATH}${query ? `?${query}` : ""}${hash}`;
}
