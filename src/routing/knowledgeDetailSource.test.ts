import { describe, expect, it } from "vitest";
import { readKnowledgeDetailSource } from "./knowledgeDetailSource";

describe("knowledge detail source", () => {
  it("keeps an explicit internal source including its query context", () => {
    expect(
      readKnowledgeDetailSource({
        backTo: "/knowledge?scope=project&project_id=p1&directory_key=project.deliverables&page=2",
        backLabel: "返回 03 交付成果",
        source: "directory",
      }),
    ).toEqual({
      backTo: "/knowledge?scope=project&project_id=p1&directory_key=project.deliverables&page=2",
      backLabel: "返回 03 交付成果",
      source: "directory",
    });
  });

  it.each([
    "https://evil.example/steal",
    "//evil.example/steal",
    "javascript:alert(1)",
    "/\\evil.example",
  ])("fails closed for an unsafe return target: %s", (backTo) => {
    expect(readKnowledgeDetailSource({ backTo, backLabel: "离开平台", source: "task" })).toEqual({
      backTo: "/knowledge",
      backLabel: "返回知识资产库",
      source: "directory",
    });
  });
});
