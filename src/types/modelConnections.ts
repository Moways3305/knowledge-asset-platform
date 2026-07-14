// Safe DTOs for KAP-managed external OpenAI-compatible chat connections.
export type ModelCapabilityType = "chat";
export type ModelUsageKey = "content_generation" | "project_qa";

export interface ModelConnectionTestResponseDTO {
  success: boolean;
  message: string;
  duration_ms: number;
}

export interface ModelConnectionDTO {
  model_ref: string;
  display_name: string;
  capability_type: ModelCapabilityType;
  provider: string | null;
  model_name: string;
  enabled: boolean;
  health_status: "configured" | "untested" | string;
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
}

export interface ModelUsageAssignmentsUpdateDTO {
  external_llm_default_ref?: string | null;
}
