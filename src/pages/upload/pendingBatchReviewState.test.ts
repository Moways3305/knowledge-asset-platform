import { describe, expect, it } from "vitest";
import type { PendingIngestItemDTO } from "../../types/ingest";
import type { NamingOptionsDTO } from "../../types/naming";
import { initialRows, reviewState, rowMissing, suggestedVersion } from "./pendingBatchReviewState";

const options = {
  rule_version: "rule-v1",
  default_confidentiality: "L2",
  categories: [{ id: "category-a", primary: "制度", secondary: "通用" }],
  directories: [],
} as unknown as NamingOptionsDTO;

const task = {
  id: "task-a",
  source_file_name: "source.pdf",
  suggested_title: "安全主题",
  suggested_formed_on: "2026-08-01",
  suggested_version: "v2",
  version_source: "source_filename",
  confidentiality_source: "ai_content",
  confidentiality_confidence: "high",
  suggested_confidentiality_level: "L2",
  naming_parsed_fields: {
    date: "2026-08-01",
    version: "V2",
    missing_fields: [],
    inferred_fields: [],
  },
} as unknown as PendingIngestItemDTO;

describe("pending batch review state", () => {
  it("normalizes a suggested version and initializes only governed fields", () => {
    expect(suggestedVersion(task)).toBe("V2");
    const rows = initialRows(task ? [task] : [], options, {
      [task.id]: {
        task_id: task.id,
        status: "classified",
        suggested_category_id: "category-a",
        candidate_rule_revision: "rule-v1",
      },
    } as never);
    expect(rows[task.id]).toMatchObject({
      subject: "安全主题",
      formed_on: "2026-08-01",
      version: "V2",
      category_id: "category-a",
      confidentiality_level: "L2",
    });
  });

  it("keeps company rows blocked until applicable_to is supplied", () => {
    const row = initialRows([task], options, {})[task.id];
    expect(rowMissing(row, true)).toEqual({
      field: "category_id",
      message: "请选择目录类别",
    });
    row.category_id = "category-a";
    expect(rowMissing(row, true)?.field).toBe("applicable_to");
  });

  it("marks a server preview error as an exception", () => {
    const row = initialRows([task], options, {})[task.id];
    expect(
      reviewState(
        task,
        row,
        { error_code: "naming_subject_invalid", submittable: false } as never,
        false,
        undefined,
        false,
        false,
        undefined,
      ),
    ).toBe("exception");
  });
});
