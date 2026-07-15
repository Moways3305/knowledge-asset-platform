// Safe DTOs for KAP-managed external OpenAI-compatible chat connections.
export type ModelCapabilityType = "chat";
export type ModelUsageKey = "content_generation" | "project_qa";
export type ExternalLlmErrorCategory =
  | "connection_error"
  | "authentication_error"
  | "model_unavailable"
  | "timeout"
  | "rate_limited"
  | "request_error"
  | "server_error"
  | "response_error"
  | "configuration_error";

export interface ModelConnectionTestResponseDTO {
  success: boolean;
  error_category: ExternalLlmErrorCategory | null;
  message: string;
  remediation_hint: string;
  retryable: boolean;
  duration_ms: number;
}

export interface ModelConnectionDTO {
  model_ref: string;
  display_name: string;
  capability_type: ModelCapabilityType;
  provider: string | null;
  model_name: string;
  enabled: boolean;
  health_status: "healthy" | "unhealthy" | "untested";
  last_test_succeeded_at: string | null;
  last_test_failed_at: string | null;
  last_error_category: ExternalLlmErrorCategory | null;
  available_usages: ModelUsageKey[];
  legacy_adapter: false;
}

export interface ModelConnectionListDTO {
  items: ModelConnectionDTO[];
  total: number;
  warning: string | null;
}

export interface ModelConnectionMutateDTO {
  display_name: string;
  capability_type: ModelCapabilityType;
  provider: string;
  model_name: string;
  base_url?: string | null;
  api_key?: string | null;
  enabled: boolean;
}

export interface ModelUsageSlotDTO {
  model_ref: string | null;
  display_name: string | null;
  capability_type: ModelCapabilityType | null;
}

export interface ModelUsageAssignmentsDTO {
  external_llm_default: ModelUsageSlotDTO | null;
  dependency_status: "configured" | "missing";
  dependency_message: string;
  remediation_hint: string;
}

export interface ModelUsageAssignmentsUpdateDTO {
  external_llm_default_ref?: string | null;
}
