export type KnowledgeDetailSourceType =
  | "directory"
  | "global-search"
  | "project"
  | "personal"
  | "task"
  | "notification"
  | "original-access"
  | "upload";

export interface KnowledgeDetailSourceState {
  backTo: string;
  backLabel: string;
  source: KnowledgeDetailSourceType;
}

const FALLBACK_SOURCE: KnowledgeDetailSourceState = {
  backTo: "/knowledge",
  backLabel: "返回知识资产库",
  source: "directory",
};

export function isSafeInternalPath(value: unknown): value is string {
  return (
    typeof value === "string" &&
    value.startsWith("/") &&
    !value.startsWith("//") &&
    !value.includes("\\") &&
    !Array.from(value).some((character) => character.charCodeAt(0) < 32)
  );
}

export function knowledgeDetailSource(
  backTo: string,
  backLabel: string,
  source: KnowledgeDetailSourceType,
): KnowledgeDetailSourceState {
  return { backTo, backLabel, source };
}

export function readKnowledgeDetailSource(state: unknown): KnowledgeDetailSourceState {
  if (!state || typeof state !== "object") return FALLBACK_SOURCE;
  const candidate = state as Partial<KnowledgeDetailSourceState>;
  if (!isSafeInternalPath(candidate.backTo)) return FALLBACK_SOURCE;
  if (typeof candidate.backLabel !== "string" || !candidate.backLabel.trim()) {
    return FALLBACK_SOURCE;
  }
  if (
    ![
      "directory",
      "global-search",
      "project",
      "personal",
      "task",
      "notification",
      "original-access",
      "upload",
    ].includes(candidate.source ?? "")
  ) {
    return FALLBACK_SOURCE;
  }
  return {
    backTo: candidate.backTo,
    backLabel: candidate.backLabel.trim().slice(0, 60),
    source: candidate.source as KnowledgeDetailSourceType,
  };
}
