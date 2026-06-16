// 个人知识库领域：本人个人知识列表与写动作（资产确认 / 提交到项目 / 登记验证证据）。
// 仅 owner 本人可操作；提交/候选支持 Idempotency-Key 防重复。响应只含安全治理元数据；
// 提交=待审核，候选=用户登记证据线索（系统不自动证明分享/客户验证真实发生）。
import { apiGet, apiPost, apiPut, createIdempotencyKey } from "./http";
import { mapCard } from "./knowledge";
import type { KnowledgeCardVM, KnowledgeListResponseDTO } from "../types/knowledge";
import type {
  ConfirmAssetResponseDTO,
  PersonalKnowledgeSubmissionDTO,
  SubmitToProjectRequestDTO,
  ValidationCandidateRequestDTO,
} from "../types/myKnowledge";

export async function fetchMyKnowledge(): Promise<KnowledgeCardVM[]> {
  const data = await apiGet<KnowledgeListResponseDTO>(`/api/v1/my/knowledge`);
  return data.items.map(mapCard);
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

// ---- 个人知识库管理（PBC-29；owner-only，仅安全元数据）----
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

export async function createMyKnowledgeBase(displayName?: string): Promise<PersonalKbDTO> {
  return apiPost<PersonalKbDTO>(MYKB, { display_name: displayName ?? null });
}

export async function renameMyKnowledgeBase(displayName: string): Promise<PersonalKbDTO> {
  return apiPut<PersonalKbDTO>(MYKB, { display_name: displayName });
}
