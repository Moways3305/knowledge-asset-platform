// 预览凭证 API 的 DTO 类型（IMPLEMENT-07）。

export interface PreviewIssueResponseDTO {
  credential_id: string;
  preview_type: string;
  credential_fingerprint: string;
  preview_entry_url: string;
  expires_at: string;
  credential_status: string;
}
