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
  it("uses a unique AI secondary category when the legacy primary label differs", () => {
    expect(suggestNamingCategory(parsed("客户项目", "交付成果"), categories)).toEqual({
      id: "deliverable",
      basis: "ai",
    });
  });

  it("does not guess when the AI label matches more than one option", () => {
    expect(
      suggestNamingCategory(parsed("", "交付成果"), [
        ...categories,
        { ...categories[1], id: "company-deliverable", primary: "公司资料" },
      ]),
    ).toBeNull();
  });
});
