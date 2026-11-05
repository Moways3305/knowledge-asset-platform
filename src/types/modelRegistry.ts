export type Capability = "chat" | "embedding" | "rerank";
export type ModelUsage = "business" | "knowledge";
export interface ProviderTemplate {
  id: string;
  name: string;
  base: string;
  capabilities: Capability[];
  workspace?: boolean;
}
export interface ProviderConnection {
  id: string;
  name: string;
  provider: string;
  config_version: number;
  credential_version: number;
  capabilities: Capability[];
  protocols: Record<string, string>;
  model_count: number;
  affected_models: string[];
}
export interface RegistryModel {
  id: string;
  request_id: string;
  connection_id: string;
  connection_name: string;
  provider: string;
  display_name: string;
  model_name: string;
  capability: Capability;
  dimension: number | null;
  usages: ModelUsage[];
  version: number;
  signature: string;
  test_status: string;
  test_code: string | null;
  test_message: string;
  tested_at: string | null;
  test_duration_ms: number | null;
  observed_dimension: number | null;
  bindings: Partial<
    Record<
      ModelUsage,
      { status: string; current: boolean; error_code: string | null; message: string }
    >
  >;
  external_ref: string | null;
  knowledge_ref: string | null;
  busy: boolean;
}
export interface RegistryInventory {
  connections: ProviderConnection[];
  models: RegistryModel[];
}
export interface ConnectionInput {
  request_id?: string;
  name: string;
  provider: string;
  api_key?: string;
  region?: string;
  workspace_id?: string;
  expected_version?: number;
  endpoints?: Partial<
    Record<Capability, { url: string; protocol: "openai" | "rerank" | "dashscope" }>
  >;
}
export interface RegistryModelInput {
  request_id: string;
  connection_id: string;
  display_name: string;
  model_name: string;
  capability: Capability;
  dimension: number | null;
  usages: ModelUsage[];
  expected_version?: number;
}
