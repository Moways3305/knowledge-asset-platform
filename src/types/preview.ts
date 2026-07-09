// 预览凭证 API 的 DTO 类型。

export interface PreviewIssueResponseDTO {
  credential_id: string;
  preview_type: string;
  credential_fingerprint: string;
  preview_entry_url: string;
  expires_at: string;
  credential_status: string;
}

export interface PreviewEntryVM {
  previewType: string;
  documentTitle: string;
  expiresAt: string;
  status: string;
  onlyofficeConfig: Record<string, unknown> | null;
  message: string | null;
}
