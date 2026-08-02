export type NamingScope = "project" | "company";

export interface ProjectCodeConfigDTO {
  project_id: string;
  code: string;
  enabled: boolean;
  default_confidentiality: string;
}

export interface NamingCategoryConfigDTO {
  id: string;
  scope: NamingScope;
  primary: string;
  secondary: string;
  prefix: string;
  default_confidentiality: string;
  enabled: boolean;
  sort_order: number;
}

export interface NamingRuleConfigDTO {
  schema_version: number;
  enforced: boolean;
  project_codes: ProjectCodeConfigDTO[];
  categories: NamingCategoryConfigDTO[];
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

export interface NamingOptionDTO {
  id: string;
  primary: string;
  secondary: string;
  prefix: string;
  default_confidentiality: string;
}

export interface NamingOptionsDTO {
  required: boolean;
  rule_version: number | null;
  categories: NamingOptionDTO[];
  default_confidentiality: string | null;
  message: string | null;
}

export interface NamingConfirmationDTO {
  category_id: string;
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
  notices: Array<{ kind: "exact" | "suspected"; message: string }>;
  message: string | null;
}
