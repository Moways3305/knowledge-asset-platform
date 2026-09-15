import type { PendingIngestItemDTO } from "../../types/ingest";
import type { UploadDuplicateDTO } from "../../types/ingest";
import type {
  BatchNamingPreviewItemDTO,
  BatchNamingValuesDTO,
  NamingOptionsDTO,
} from "../../types/naming";

export type ReviewRows = Record<string, BatchNamingValuesDTO>;
export type PreviewRows = Record<string, BatchNamingPreviewItemDTO>;
export type ReviewState = "ai_ready" | "manual" | "reviewed" | "exception";
export type ReviewFilter =
  | "all"
  | ReviewState
  | "missing_confidentiality"
  | "missing_date"
  | "missing_directory";
export const REVIEW_FILTERS = [
  ["all", "全部"],
  ["ai_ready", "可确认"],
  ["manual", "需处理"],
  ["reviewed", "已核对"],
  ["exception", "异常/重复"],
  ["missing_confidentiality", "缺密级"],
  ["missing_date", "缺日期"],
  ["missing_directory", "待选目录"],
] as const;
export function matchesReviewFilter(
  filter: ReviewFilter,
  state: ReviewState,
  row: BatchNamingValuesDTO | undefined,
): boolean {
  if (filter === "all") return true;
  if (filter === "missing_confidentiality")
    return !CONFIDENTIALITY_LEVELS.has(row?.confidentiality_level ?? "");
  if (filter === "missing_date") return !DATE_PATTERN.test(row?.formed_on ?? "");
  if (filter === "missing_directory") return !row?.directory_key;
  return filter === state;
}

// Match explicit historical category labels to the current formal directory.
// Inferred/missing labels and ambiguous matches are not classification evidence.
export function suggestedDirectory(task: PendingIngestItemDTO, options: NamingOptionsDTO): string {
  const parsed = task.naming_parsed_fields;
  if (!parsed) return "";
  const unsafe = new Set([...(parsed.inferred_fields ?? []), ...(parsed.missing_fields ?? [])]);
  const clean = (s: string) =>
    s
      .trim()
      .replace(/^\d+\s*/, "")
      .trim();
  const labels = ["primary_category", "secondary_category"] as const;
  const names = new Set(
    labels
      .filter((key) => !unsafe.has(key))
      .map((key) => clean(parsed[key] ?? ""))
      .filter(Boolean),
  );
  const matches = options.directories.filter((d) => d.enabled && names.has(clean(d.display_name)));
  return matches.length === 1 ? matches[0].directory_key : "";
}
export type DeleteFeedback = { message: string; retryable: boolean };
export type CompletedReviewItem = {
  taskId: string;
  title: string;
  assetId?: string;
  indexStatus?: string;
};
export type SkippedDuplicateItem = {
  task: PendingIngestItemDTO;
  duplicate: UploadDuplicateDTO;
};

export const DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/;
const VERSION_PATTERN = /^V[1-9]\d*(?:\.\d+)*$/;
const CONFIDENTIALITY_LEVELS = new Set(["L1", "L2", "L3", "L4", "L5"]);

export function parsedValue(task: PendingIngestItemDTO, field: "date" | "version"): string {
  const parsed = task.naming_parsed_fields;
  if (!parsed || parsed.missing_fields?.includes(field)) return "";
  const value = parsed[field]?.trim() ?? "";
  if (field === "date") {
    if (DATE_PATTERN.test(value)) return value;
    if (/^\d{8}$/.test(value)) return `${value.slice(0, 4)}-${value.slice(4, 6)}-${value.slice(6)}`;
    return "";
  }
  return VERSION_PATTERN.test(value.toUpperCase()) ? value.toUpperCase() : "";
}

export function sourceSubject(task: PendingIngestItemDTO): string {
  // The backend remains authoritative for canonical rendering. Never initialize
  // the filename subject from the unrelated AI topic suggestion.
  const name = task.source_file_name.trim();
  const dot = name.lastIndexOf(".");
  return dot > 0 ? name.slice(0, dot) : name;
}

export function suggestedVersion(task: PendingIngestItemDTO): string {
  const value = task.suggested_version?.trim().toUpperCase() ?? "";
  return VERSION_PATTERN.test(value) ? value : "V1";
}

export function hasReliableAiConfidentiality(
  task: Pick<
    PendingIngestItemDTO,
    "confidentiality_source" | "confidentiality_confidence" | "suggested_confidentiality_level"
  >,
): boolean {
  return (
    task.confidentiality_source === "ai_content" &&
    (task.confidentiality_confidence === "high" || task.confidentiality_confidence === "medium") &&
    CONFIDENTIALITY_LEVELS.has(task.suggested_confidentiality_level ?? "")
  );
}

export function suggestedConfidentiality(
  task: PendingIngestItemDTO,
  _options: NamingOptionsDTO,
  _directoryKey?: string,
): string {
  if (hasReliableAiConfidentiality(task)) return task.suggested_confidentiality_level!;
  return "";
}

export function initialRows(tasks: PendingIngestItemDTO[], options: NamingOptionsDTO): ReviewRows {
  return Object.fromEntries(
    tasks.map((task) => {
      const defaultDirectoryKey = suggestedDirectory(task, options);
      return [
        task.id,
        {
          directory_key: defaultDirectoryKey,
          subject: sourceSubject(task),
          formed_on: task.suggested_formed_on?.match(/^\d{4}-\d{2}-\d{2}$/)
            ? task.suggested_formed_on
            : "",
          version: suggestedVersion(task),
          applicable_to: "通用",
          confidentiality_level: suggestedConfidentiality(task, options, defaultDirectoryKey),
        },
      ];
    }),
  );
}

export type NamingField =
  | "subject"
  | "directory_key"
  | "formed_on"
  | "version"
  | "applicable_to"
  | "confidentiality_level";

export type RowError = { field: NamingField | null; message: string };

export function rowMissing(row: BatchNamingValuesDTO, company: boolean): RowError | null {
  if (!CONFIDENTIALITY_LEVELS.has(row.confidentiality_level))
    return { field: "confidentiality_level", message: "请选择密级" };
  if (!row.subject.trim()) return { field: "subject", message: "请填写主题" };
  if (!row.directory_key) return { field: "directory_key", message: "请选择正式目录" };
  if (!DATE_PATTERN.test(row.formed_on)) {
    return { field: "formed_on", message: "请填写文件最后修改日期" };
  }
  if (!VERSION_PATTERN.test(row.version.toUpperCase())) {
    return { field: "version", message: "请填写有效版本，例如 V1" };
  }
  if (company && !row.applicable_to?.trim()) {
    return { field: "applicable_to", message: "请填写适用对象" };
  }
  return null;
}

export function previewError(preview: BatchNamingPreviewItemDTO | undefined): RowError | null {
  if (!preview?.message || preview.submittable) return null;
  const fields: Partial<Record<string, NamingField>> = {
    naming_subject_invalid: "subject",
    naming_directory_unavailable: "directory_key",
    naming_formed_on_invalid: "formed_on",
    naming_version_invalid: "version",
    naming_applicable_to_required: "applicable_to",
  };
  return { field: fields[preview.error_code ?? ""] ?? null, message: preview.message };
}

export function reviewState(
  _task: PendingIngestItemDTO,
  row: BatchNamingValuesDTO,
  preview: BatchNamingPreviewItemDTO | undefined,
  company: boolean,
  flowError: string | undefined,
  _edited: boolean,
  reviewed: boolean,
): ReviewState {
  if (flowError) return "exception";
  if (rowMissing(row, company)) return "manual";
  if (preview?.error_code) return "exception";
  const duplicate = preview?.duplicate;
  if (
    duplicate &&
    duplicate.duplicate_state !== "none" &&
    duplicate.duplicate_state !== "suspected_metadata" &&
    duplicate.decision !== "independent" &&
    !(duplicate.duplicate_state === "same_batch" && duplicate.default_selected)
  )
    return "exception";
  if (!preview?.submittable) return "manual";
  return reviewed ? "reviewed" : "ai_ready";
}
