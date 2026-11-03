import { apiGet } from "./http";
import type { AgentCitationDTO } from "../types/agent";

// Explicit operator tools; the server remains the permission authority.
export interface AgentCallDetail {
  call_id: string;
  caller_name: string;
  project_name: string;
  query_text: string;
  response_text: string | null;
  call_status: string;
  denied_reason: string | null;
  citations: AgentCitationDTO[];
  created_at: string;
}

export interface AgentDecisions {
  decision_status: string;
  items: {
    target_asset_id: string;
    discovery_allowed: boolean;
    summary_allowed: boolean;
    original_allowed: boolean;
    returned_layer: string;
    denied_reason: string | null;
  }[];
}

export function fetchAgentCall(callId: string) {
  return apiGet<AgentCallDetail>(`/api/v1/agent-calls/${encodeURIComponent(callId)}`);
}

export function fetchAgentDecisions(callId: string) {
  return apiGet<AgentDecisions>(`/api/v1/agent-calls/${encodeURIComponent(callId)}/decision-items`);
}
