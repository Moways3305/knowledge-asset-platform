import { apiGet, BASE_URL, csrfHeaders, handleResponse, withCsrfRetry } from "./http";
import type { IngestUploadResponseDTO } from "../types/ingest";
import { localDateFromMs } from "./ingest";

export interface VersionItem {
  asset_id: string;
  version_id: string;
  title: string;
  version: string;
  status: string;
  version_status: string;
  created_at: string;
  is_current: boolean;
}
export interface VersionHistory {
  asset_id: string;
  updated_at: string;
  current_asset_id: string | null;
  can_update: boolean;
  suggested_version: string;
  items: VersionItem[];
  truncated: boolean;
  updates: Array<{
    task_id: string;
    version: string;
    status: string;
    result_asset_id: string | null;
    can_replace: boolean;
  }>;
}
export interface VersionComparison {
  left: { version: string; directory: string | null; summary: string | null };
  right: { version: string; directory: string | null; summary: string | null };
  changed_fields: string[];
  scope: string;
}
export const fetchVersionHistory = (id: string) =>
  apiGet<VersionHistory>(`/api/v1/knowledge/${id}/versions`);
export const compareVersions = (id: string, left: string, right: string) =>
  apiGet<VersionComparison>(
    `/api/v1/knowledge/${id}/versions/compare?left=${encodeURIComponent(left)}&right=${encodeURIComponent(right)}`,
  );
export async function uploadVersion(id: string, file: File, stamp: string, version: string) {
  const body = new FormData();
  body.append("file", file, file.name);
  const formedOn = localDateFromMs(file.lastModified);
  if (formedOn) body.append("formed_on", formedOn);
  body.append("expected_updated_at", stamp);
  body.append("update_of_asset_id", id);
  body.append("version_label", version);
  return withCsrfRetry(async () =>
    handleResponse<IngestUploadResponseDTO>(
      await fetch(`${BASE_URL}/api/v1/ingest/upload`, {
        method: "POST",
        body,
        credentials: "include",
        headers: await csrfHeaders(),
      }),
    ),
  );
}
