import { apiGet, apiPatch, apiPost, apiPut, createIdempotencyKey } from "./http";
import { mapCard } from "./knowledge";
import type {
  ConfirmAssetResponseDTO,
  PersonalKnowledgeItemDTO,
  PersonalKnowledgeItemVM,
  PersonalKnowledgeListDTO,
  PersonalKnowledgePageVM,
  PersonalKnowledgeQuery,
  PersonalKnowledgeSubmissionDTO,
  PersonalKnowledgeUpdateRequestDTO,
  SubmitToProjectRequestDTO,
  ValidationCandidateRequestDTO,
} from "../types/myKnowledge";

function mapPersonalItem(data: PersonalKnowledgeItemDTO): PersonalKnowledgeItemVM {
  return {
    ...mapCard(data),
    updatedAt: data.updated_at ?? "",
    createdAt: data.created_at,
    personalState: data.personal_state,
    personalStateLabel: data.personal_state_label,
    projectSubmission: data.project_submission,
    evidenceSummary: data.evidence_summary,
  };
}

export async function fetchMyKnowledge(
  query: PersonalKnowledgeQuery = {},
): Promise<PersonalKnowledgePageVM> {
  const params = new URLSearchParams();
  if (query.page) params.set("page", String(query.page));
  if (query.pageSize) params.set("page_size", String(query.pageSize));
  if (query.keyword) params.set("keyword", query.keyword);
  if (query.assetType) params.set("asset_type", query.assetType);
  if (query.personalState) params.set("personal_state", query.personalState);
  if (query.sortBy) params.set("sort_by", query.sortBy);
  if (query.sortDirection) params.set("sort_direction", query.sortDirection);
  const suffix = params.size ? `?${params.toString()}` : "";
  const data = await apiGet<PersonalKnowledgeListDTO>(`/api/v1/my/knowledge${suffix}`);
  return {
    items: data.items.map(mapPersonalItem),
    total: data.total,
    page: data.page,
    pageSize: data.page_size,
    hasNext: data.has_next,
    summary: data.summary,
  };
}

export async function updatePersonalKnowledge(
  assetId: string,
  body: PersonalKnowledgeUpdateRequestDTO,
): Promise<PersonalKnowledgeItemVM> {
  return mapPersonalItem(
    await apiPatch<PersonalKnowledgeItemDTO>(`/api/v1/my/knowledge/${assetId}`, body),
  );
}

export async function confirmPersonalAsset(assetId: string): Promise<ConfirmAssetResponseDTO> {
  return apiPost<ConfirmAssetResponseDTO>(`/api/v1/my/knowledge/${assetId}/confirm-asset`, {});
}

export async function submitPersonalKnowledge(
  assetId: string,
  body: SubmitToProjectRequestDTO,
): Promise<PersonalKnowledgeSubmissionDTO> {
  return apiPost<PersonalKnowledgeSubmissionDTO>(
    `/api/v1/my/knowledge/${assetId}/submit-to-project`,
    body,
    { "Idempotency-Key": createIdempotencyKey() },
  );
}

export async function registerPersonalKnowledgeEvidence(
  assetId: string,
  body: ValidationCandidateRequestDTO,
): Promise<PersonalKnowledgeSubmissionDTO> {
  return apiPost<PersonalKnowledgeSubmissionDTO>(
    `/api/v1/my/knowledge/${assetId}/validation-evidence`,
    body,
    { "Idempotency-Key": createIdempotencyKey() },
  );
}

export interface PersonalKbDTO {
  exists: boolean;
  display_name?: string | null;
  status?: string | null;
  knowledge_count?: number;
  index_distribution?: Record<string, number>;
  embedding_model_ref?: string | null;
  created_at?: string | null;
  weknora_sync_failed?: boolean;
}

const MYKB = "/api/v1/my/knowledge-base";

export async function fetchMyKnowledgeBase(): Promise<PersonalKbDTO> {
  return apiGet<PersonalKbDTO>(MYKB);
}

export async function createMyKnowledgeBase(input?: {
  displayName?: string;
  embeddingModelRef?: string;
  rerankModelRef?: string;
}): Promise<PersonalKbDTO> {
  return apiPost<PersonalKbDTO>(MYKB, {
    display_name: input?.displayName ?? null,
    embedding_model_ref: input?.embeddingModelRef || undefined,
    rerank_model_ref: input?.rerankModelRef || undefined,
  });
}

export async function renameMyKnowledgeBase(displayName: string): Promise<PersonalKbDTO> {
  return apiPut<PersonalKbDTO>(MYKB, { display_name: displayName });
}
