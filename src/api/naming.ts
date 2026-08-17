import { apiGet, apiPost, apiPut } from "./http";
import type {
  BatchNamingPreviewResponseDTO,
  BatchNamingValuesDTO,
  CategoryClassificationBatchDTO,
  CategoryClassificationItemDTO,
  NamingConfirmationDTO,
  NamingOptionsDTO,
  NamingPreviewDTO,
  NamingRuleCenterDTO,
  NamingRuleConfigDTO,
  NamingRuleRevisionDTO,
  DirectoryMigrationWorkspaceDTO,
} from "../types/naming";

export function fetchDirectoryMigration(
  params: {
    scope?: string;
    projectId?: string;
    status?: string;
  } = {},
): Promise<DirectoryMigrationWorkspaceDTO> {
  const qs = new URLSearchParams();
  if (params.scope) qs.set("scope", params.scope);
  if (params.projectId) qs.set("project_id", params.projectId);
  if (params.status) qs.set("status", params.status);
  return apiGet(`/api/v1/admin/directory-migration?${qs.toString()}`);
}

export function confirmDirectoryMigration(
  items: Array<{ candidate_id: string; directory_key?: string }>,
): Promise<{ submitted: number; migrated: number; skipped: number; failed: number }> {
  return apiPost("/api/v1/admin/directory-migration/confirm", { items });
}

export function fetchNamingRuleCenter(): Promise<NamingRuleCenterDTO> {
  return apiGet("/api/v1/admin/naming-rules");
}

export function saveNamingRuleDraft(
  expectedBaseVersion: number,
  config: NamingRuleConfigDTO,
): Promise<NamingRuleRevisionDTO> {
  return apiPut("/api/v1/admin/naming-rules/draft", {
    expected_base_version: expectedBaseVersion,
    config,
  });
}

export function publishNamingRuleDraft(expectedBaseVersion: number): Promise<NamingRuleCenterDTO> {
  return apiPost("/api/v1/admin/naming-rules/publish", {
    expected_base_version: expectedBaseVersion,
  });
}

export function fetchNamingOptions(
  scope: "personal" | "project" | "company",
  projectId?: string,
): Promise<NamingOptionsDTO> {
  const params = new URLSearchParams({ scope });
  if (projectId) params.set("project_id", projectId);
  return apiGet(`/api/v1/naming-options?${params.toString()}`);
}

export function previewIngestNaming(
  taskId: string,
  input: {
    target_scope: "personal" | "project" | "company";
    target_project_id?: string;
    confidentiality_level: string;
    naming?: NamingConfirmationDTO;
  },
): Promise<NamingPreviewDTO> {
  return apiPost(`/api/v1/ingest/${taskId}/naming-preview`, input);
}

export function previewBatchIngestNaming(input: {
  targetScope: "project" | "company";
  targetProjectId?: string;
  items: Array<{ taskId: string; naming: BatchNamingValuesDTO }>;
}): Promise<BatchNamingPreviewResponseDTO> {
  return apiPost("/api/v1/ingest/bulk-naming-preview", {
    target_scope: input.targetScope,
    target_project_id: input.targetProjectId ?? null,
    items: input.items.map((item) => ({
      task_id: item.taskId,
      confidentiality_level: item.naming.confidentiality_level,
      naming: {
        category_id: item.naming.category_id,
        subject: item.naming.subject,
        formed_on: item.naming.formed_on,
        version: item.naming.version,
        ...(item.naming.directory_key ? { directory_key: item.naming.directory_key } : {}),
        ...(item.naming.directory_fallback_confirmed ? { directory_fallback_confirmed: true } : {}),
        ...(input.targetScope === "company" ? { applicable_to: item.naming.applicable_to } : {}),
      },
    })),
  });
}

export function classifyBatchNamingCategories(input: {
  taskIds: string[];
  targetScope: "project" | "company";
  targetProjectId?: string;
  retry?: boolean;
}): Promise<CategoryClassificationBatchDTO> {
  return apiPost("/api/v1/ingest/bulk-category-classification", {
    task_ids: input.taskIds,
    target_scope: input.targetScope,
    target_project_id: input.targetProjectId ?? null,
    retry: input.retry ?? false,
  });
}

export function saveManualNamingCategory(input: {
  taskId: string;
  targetScope: "project" | "company";
  targetProjectId?: string;
  categoryId: string;
}): Promise<CategoryClassificationItemDTO> {
  return apiPut(`/api/v1/ingest/${input.taskId}/category-selection`, {
    target_scope: input.targetScope,
    target_project_id: input.targetProjectId ?? null,
    category_id: input.categoryId,
  });
}
