import { apiGet, apiPost, apiPut } from "./http";

export type ReleaseKind = "new" | "improved" | "fixed";
export interface ReleaseEntry {
  kind: ReleaseKind;
  text: string;
}
export interface ReleaseDraft {
  version: string;
  title: string;
  entries: ReleaseEntry[];
  notify_users: boolean;
}
export interface ReleaseNote extends ReleaseDraft {
  id: string;
  revision: number;
  created_at: string;
  updated_at: string;
  published_at: string | null;
  is_unread: boolean;
  source_commit?: string | null;
  previous_commit?: string | null;
  deployed_at?: string | null;
}
export interface ReleaseList {
  items: ReleaseNote[];
  total: number;
  page: number;
  page_size: number;
}
export interface ReleaseStatus {
  running_version: string;
  unread_count: number;
}
export const RELEASE_NOTES_CHANGED = "kap:release-notes-changed";
export function invalidateReleaseNotes() {
  window.dispatchEvent(new Event(RELEASE_NOTES_CHANGED));
}
export function fetchReleaseStatus(signal?: AbortSignal): Promise<ReleaseStatus> {
  return apiGet("/api/v1/release-notes/status", signal);
}
export function fetchReleaseNotes(
  page: number,
  state?: "draft" | "published",
  signal?: AbortSignal,
): Promise<ReleaseList> {
  return apiGet(
    `/api/v1/${state ? "admin/" : ""}release-notes?page=${page}&page_size=10${state ? `&state=${state}` : ""}`,
    signal,
  );
}
export function saveReleaseNote(body: ReleaseDraft, note?: ReleaseNote): Promise<ReleaseNote> {
  return note
    ? apiPut(`/api/v1/admin/release-notes/${note.id}`, { ...body, revision: note.revision })
    : apiPost("/api/v1/admin/release-notes", body);
}
export function publishReleaseNote(note: ReleaseNote): Promise<ReleaseNote> {
  return apiPost(`/api/v1/admin/release-notes/${note.id}/publish`, { revision: note.revision });
}
export function readReleaseNotes(ids: string[]): Promise<ReleaseStatus> {
  return apiPost("/api/v1/release-notes/read", { release_ids: ids });
}
