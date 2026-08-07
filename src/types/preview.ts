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
  // pdf / image / markdown / text / office——前端据此选择渲染器。
  renderType?: string | null;
  // 平台受控取件相对路径（含短时 token，凭证有效期内可读）。
  fileUrl?: string | null;
  onlyofficeConfig: Record<string, unknown> | null;
  message: string | null;
}
