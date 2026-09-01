export type NamingScope = "project" | "company";
export type NamingAssetType =
  | "deliverable"
  | "methodology"
  | "case"
  | "template"
  | "insight"
  | "unclassified";

export interface ProjectCodeConfigDTO {
  project_id: string;
  code: string;
  enabled: boolean;
  default_confidentiality: string;
  client_aliases?: string[];
  client_aliases_enabled?: boolean;
}

export interface NamingCategoryConfigDTO {
  id: string;
  scope: NamingScope;
  primary: string;
  secondary: string;
  prefix: string;
  asset_type: NamingAssetType | null;
  description?: string | null;
  default_confidentiality: string;
  enabled: boolean;
  sort_order: number;
  suggested_directory_key?: string | null;
}

export interface DirectoryOptionDTO {
  directory_key: string;
  scope: "personal" | "project" | "company";
  display_name: string;
  description?: string | null;
  naming_code?: string | null;
  default_confidentiality?: string | null;
  sort_order: number;
  enabled: boolean;
}

export interface NamingRuleConfigDTO {
  schema_version: number;
  enforced: boolean;
  project_codes: ProjectCodeConfigDTO[];
  categories: NamingCategoryConfigDTO[];
  directories?: DirectoryOptionDTO[];
  migration_missing_asset_type_category_ids?: string[];
}

export interface NamingRuleRevisionDTO {
  version: number;
  status: string;
  base_published_version: number;
  config: NamingRuleConfigDTO;
  updated_at: string;
  published_at: string | null;
}

export interface NamingRuleCenterDTO {
  published: NamingRuleRevisionDTO;
  draft: NamingRuleRevisionDTO;
  projects: Array<{
    id: string;
    name: string;
    status: string;
    project_code: string | null;
    project_code_active: boolean;
    default_confidentiality: string;
  }>;
}

export interface DirectoryMigrationWorkspaceDTO {
  overview: {
    total: number;
    migrated: number;
    clear_match: number;
    manual_required: number;
    no_candidate: number;
    failed: number;
    rule_version: number | null;
  };
  items: Array<{
    id: string;
    asset_title: string;
    scope: string;
    project_id: string | null;
    project_name: string | null;
    old_category: string | null;
    suggested_directory_key: string | null;
    suggested_directory_name: string | null;
    candidate_source: string;
    confidence: string;
    status: string;
    failure_code: string | null;
    updated_at: string | null;
  }>;
  total: number;
  directories: DirectoryOptionDTO[];
}

export interface NamingOptionsDTO {
  required: boolean;
  rule_version: number | null;
  directories: DirectoryOptionDTO[];
  default_confidentiality: string | null;
  message: string | null;
}

export interface NamingConfirmationDTO {
  directory_key: string;
  subject: string;
  formed_on: string;
  version: string;
  applicable_to?: string;
}

export interface NamingPreviewDTO {
  required: boolean;
  canonical_name: string | null;
  rule_version: number | null;
  fields: Record<string, unknown> | null;
  notices: NamingWarningNoticeDTO[];
  message: string | null;
  suggested_version?: string;
  version_source?: "source_filename" | "ai_content" | "default_needs_confirmation";
  version_confidence?: "high" | "medium" | "low";
  version_reason?: string;
  suggested_confidentiality_level?: string;
  confidentiality_source?: "ai_content" | "default_needs_confirmation";
  confidentiality_confidence?: "high" | "medium" | "low";
  confidentiality_reason?: string;
  duplicate?: import("./ingest").UploadDuplicateDTO;
}

export interface NamingWarningNoticeDTO {
  code?:
    | "project_subject_business_name"
    | "exact_duplicate"
    | "suspected_duplicate"
    | "version_source_unreliable"
    | "confidentiality_source_unreliable"
    | "historical_naming_noncompliant"
    | "ai_suggestion_uncertain";
  kind: "exact" | "suspected" | "semantic" | "advisory";
  message: string;
}

export interface BatchNamingValuesDTO {
  directory_key: string;
  subject: string;
  formed_on: string;
  version: string;
  applicable_to?: string;
  confidentiality_level: string;
}

export interface BatchNamingPreviewItemDTO {
  task_id: string;
  submittable: boolean;
  canonical_name: string | null;
  rule_version: number | null;
  fields: Record<string, unknown> | null;
  notices: NamingWarningNoticeDTO[];
  error_code: string | null;
  message: string | null;
  suggested_version?: string;
  version_source?: "source_filename" | "ai_content" | "default_needs_confirmation";
  version_confidence?: "high" | "medium" | "low";
  version_reason?: string;
  suggested_confidentiality_level?: string;
  confidentiality_source?: "ai_content" | "default_needs_confirmation";
  confidentiality_confidence?: "high" | "medium" | "low";
  confidentiality_reason?: string;
  duplicate?: import("./ingest").UploadDuplicateDTO;
}

export interface BatchNamingPreviewResponseDTO {
  items: BatchNamingPreviewItemDTO[];
}
