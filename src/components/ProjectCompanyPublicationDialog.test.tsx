import { describe, expect, it } from "vitest";
import { getProjectCompanyPublicationEligibility } from "./ProjectCompanyPublicationDialog";

const candidate = {
  scope: "project",
  zone: "asset",
  assetStatus: "active" as const,
  projectId: "project-a",
};

describe("project company publication eligibility", () => {
  it.each([
    ["project_manager", candidate, true, null],
    ["consultant", candidate, false, "仅项目经理可提交公司发布申请"],
    ["admin", candidate, false, "仅项目经理可提交公司发布申请"],
    ["project_manager", { ...candidate, zone: "material" }, false, "资料需先完成资产化审核"],
    [
      "project_manager",
      { ...candidate, assetStatus: "archived" as const },
      false,
      "已归档资产不能提交公司发布申请",
    ],
    [
      "project_manager",
      { ...candidate, assetStatus: "needs_update" as const },
      false,
      "仅活跃项目资产可提交公司发布申请",
    ],
    [
      "project_manager",
      { ...candidate, projectId: "project-b" },
      false,
      "仅可发布当前项目内的知识资产",
    ],
  ])("enforces the role and asset-state matrix", (role, input, eligible, reason) => {
    expect(getProjectCompanyPublicationEligibility(input, "project-a", role)).toEqual({
      eligible,
      reason,
    });
  });
});
