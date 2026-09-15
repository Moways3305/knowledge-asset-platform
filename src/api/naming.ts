import { apiGet, apiPost, apiPut } from "./http";
import type {
  BatchNamingPreviewResponseDTO,
  BatchNamingValuesDTO,
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
    directories: config.directories ?? [],
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

export async function previewBatchIngestNaming(input: {
  targetScope: "project" | "company";
  targetProjectId?: string;
  items: Array<{ taskId: string; naming: BatchNamingValuesDTO }>;
}): Promise<BatchNamingPreviewResponseDTO> {
  const result: BatchNamingPreviewResponseDTO = { items: [] };
  // Large review sessions must not exceed the endpoint's 500-item contract.
  // Smaller sequential requests also bound work for hundreds of files.
  for (let offset = 0; offset < input.items.length; offset += 50) {
    const response = await apiPost<BatchNamingPreviewResponseDTO>(
      "/api/v1/ingest/bulk-naming-preview",
      {
        target_scope: input.targetScope,
        target_project_id: input.targetProjectId ?? null,
        items: input.items.slice(offset, offset + 50).map((item) => ({
          task_id: item.taskId,
          confidentiality_level: item.naming.confidentiality_level,
          naming: {
            directory_key: item.naming.directory_key,
            subject: item.naming.subject,
            ...(item.naming.subject_is_manual ? { subject_is_manual: true } : {}),
            formed_on: item.naming.formed_on,
            version: item.naming.version,
            ...(input.targetScope === "company"
              ? { applicable_to: item.naming.applicable_to }
              : {}),
          },
        })),
      },
    );
    result.items.push(...response.items);
  }
  return result;
}
