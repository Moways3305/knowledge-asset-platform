import type { PendingIngestItemDTO } from "../../types/ingest";
import type { UploadDuplicateDTO } from "../../types/ingest";
import type {
  BatchNamingPreviewItemDTO,
  BatchNamingValuesDTO,
  NamingOptionsDTO,
} from "../../types/naming";

export type ReviewRows = Record<string, BatchNamingValuesDTO>;
export type PreviewRows = Record<string, BatchNamingPreviewItemDTO>;
export type ReviewFilter = "all" | "ai_ready" | "manual" | "reviewed" | "exception";
export type ReviewState = Exclude<ReviewFilter, "all">;
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
  // The original filename is displayed as source context only. Do not turn it
  // into a governed subject unless the backend has already projected a safe suggestion.
  return task.suggested_title?.trim() || "";
}

export function suggestedVersion(task: PendingIngestItemDTO): string {
  const value = task.suggested_version?.trim().toUpperCase() ?? "";
  return VERSION_PATTERN.test(value) ? value : "V1";
}

export function hasReliableAiConfidentiality(task: PendingIngestItemDTO): boolean {
  return (
    task.confidentiality_source === "ai_content" &&
    (task.confidentiality_confidence === "high" || task.confidentiality_confidence === "medium") &&
    CONFIDENTIALITY_LEVELS.has(task.suggested_confidentiality_level ?? "")
  );
}

export function suggestedConfidentiality(
  task: PendingIngestItemDTO,
  options: NamingOptionsDTO,
  directoryKey?: string,
): string {
  if (hasReliableAiConfidentiality(task)) return task.suggested_confidentiality_level!;
  return directoryDefaultConfidentiality(options, directoryKey);
}

export function directoryDefaultConfidentiality(
  options: NamingOptionsDTO,
  directoryKey?: string,
): string {
  return (
    options.directories.find((directory) => directory.directory_key === directoryKey)
      ?.default_confidentiality ||
    options.default_confidentiality ||
    "L2"
  );
}

export function initialRows(tasks: PendingIngestItemDTO[], options: NamingOptionsDTO): ReviewRows {
  const defaultDirectoryKey =
    options.directories.find((directory) => directory.enabled)?.directory_key ?? "";
  return Object.fromEntries(
    tasks.map((task) => {
      return [
        task.id,
        {
          directory_key: defaultDirectoryKey,
          subject: sourceSubject(task),
          formed_on:
            (task.suggested_formed_on?.match(/^\d{4}-\d{2}-\d{2}$/)
              ? task.suggested_formed_on
              : "") || parsedValue(task, "date"),
          version: suggestedVersion(task),
          applicable_to: "",
          confidentiality_level: suggestedConfidentiality(task, options, defaultDirectoryKey),
        },
      ];
    }),
  );
}

export type NamingField = "subject" | "directory_key" | "formed_on" | "version" | "applicable_to";

export type RowError = { field: NamingField | null; message: string };

export function rowMissing(row: BatchNamingValuesDTO, company: boolean): RowError | null {
  if (!row.subject.trim()) return { field: "subject", message: "请填写主题" };
  if (!row.directory_key) return { field: "directory_key", message: "请选择正式目录" };
  if (!DATE_PATTERN.test(row.formed_on)) {
    return { field: "formed_on", message: "请填写文件形成日期" };
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
  task: PendingIngestItemDTO,
  row: BatchNamingValuesDTO,
  preview: BatchNamingPreviewItemDTO | undefined,
  company: boolean,
  flowError: string | undefined,
  edited: boolean,
  reviewed: boolean,
): ReviewState {
  if (preview?.error_code) return "exception";
  if (flowError) return "exception";
  if (rowMissing(row, company)) return "manual";
  if (reviewed) return "reviewed";
  if (edited) return "manual";

  const parsed = task.naming_parsed_fields;
  const legacyCategoryFields = new Set(["primary_category", "secondary_category", "asset_type"]);
  const unsafeAiField = Boolean(
    parsed &&
    [...(parsed.missing_fields ?? []), ...(parsed.inferred_fields ?? [])].some(
      (field) => !legacyCategoryFields.has(field),
    ),
  );
  const differsFromSafeAi =
    row.subject.trim() !== sourceSubject(task) ||
    row.formed_on !== parsedValue(task, "date") ||
    row.version.toUpperCase() !== suggestedVersion(task);
  if (
    !parsed ||
    unsafeAiField ||
    differsFromSafeAi ||
    (task.version_source !== "source_filename" && task.version_source !== "ai_content") ||
    !hasReliableAiConfidentiality(task) ||
    (company && !row.applicable_to)
  ) {
    return "manual";
  }
  return "ai_ready";
}
