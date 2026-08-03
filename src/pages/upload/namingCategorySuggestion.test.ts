import { describe, expect, it } from "vitest";

import type { NamingFields } from "../../types/ingest";
import type { NamingOptionDTO } from "../../types/naming";
import { suggestNamingCategory } from "./namingCategorySuggestion";

const categories: NamingOptionDTO[] = [
  {
    id: "foundation",
    primary: "项目资料",
    secondary: "项目基础信息",
    prefix: "项目资料-项目基础信息",
    default_confidentiality: "L2",
  },
  {
    id: "deliverable",
    primary: "项目资料",
    secondary: "交付成果",
    prefix: "项目资料-交付成果",
    default_confidentiality: "L2",
  },
];

function parsed(primary: string, secondary: string): NamingFields {
  return {
    primary_category: primary,
    secondary_category: secondary,
    topic: "经营目标与平衡计分卡KPI表",
    subject_or_client: "",
    date: "20210307",
    version: "V1",
    confidentiality_level: "L2",
    ai_access_level: "A2",
    normalized_title: "",
    inferred_fields: ["secondary_category"],
    missing_fields: [],
    source_file_name: "经营目标表.md",
    original_naming_compliant: false,
  };
}

describe("suggestNamingCategory", () => {
  it("uses only a persisted AI-content category from the current rule revision", () => {
    const naming = parsed("客户项目", "交付成果");
    naming.category_suggestion = {
      suggested_category_id: "deliverable",
      category_source: "ai_content",
      category_confidence: "high",
      category_reason: "AI 根据正文语义匹配",
      candidate_rule_revision: 3,
      status: "classified",
    };
    expect(suggestNamingCategory(naming, categories, 3)).toEqual({
      id: "deliverable",
      basis: "ai",
    });
  });

  it("never maps legacy primary or secondary labels without a proven source", () => {
    expect(suggestNamingCategory(parsed("项目资料", "交付成果"), categories, 3)).toBeNull();
  });

  it("invalidates a persisted suggestion when the rule revision changes", () => {
    const naming = parsed("", "");
    naming.category_suggestion = {
      suggested_category_id: "deliverable",
      category_source: "rule_only_option",
      category_confidence: "high",
      category_reason: "规则唯一选项",
      candidate_rule_revision: 2,
      status: "classified",
    };
    expect(suggestNamingCategory(naming, categories, 3)).toBeNull();
  });
});
