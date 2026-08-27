/** Network command boundary for the governed pending-batch workflow. */
import { ApiError } from "../../api/http";
export { decideUploadDuplicate, fetchIngestAiResult, retryIngestTask } from "../../api/ingest";
export {
  classifyBatchNamingCategories,
  fetchNamingOptions,
  previewBatchIngestNaming,
  previewIngestNaming,
  saveManualNamingCategory,
} from "../../api/naming";

export function commandErrorMessage(error: unknown, fallback: string): string {
  return error instanceof ApiError ? error.message : fallback;
}

export function commandErrorMatches(
  error: unknown,
  expected: { status?: number; deniedReason?: string },
): boolean {
  return (
    error instanceof ApiError &&
    (expected.status === undefined || error.status === expected.status) &&
    (expected.deniedReason === undefined || error.deniedReason === expected.deniedReason)
  );
}
