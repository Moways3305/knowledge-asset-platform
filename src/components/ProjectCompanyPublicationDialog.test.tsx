import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import ProjectCompanyPublicationDialog, {
  getProjectCompanyPublicationEligibility,
} from "./ProjectCompanyPublicationDialog";
import { createPublicationNamingValue } from "./PublicationNamingFields";
import { fetchNamingOptions } from "../api/naming";
import { previewCompanyUpgrade, requestCompanyUpgrade } from "../api/review";
import type { NamingPreviewDTO } from "../types/naming";

vi.mock("../api/naming", () => ({ fetchNamingOptions: vi.fn() }));
vi.mock("../api/review", () => ({
  previewCompanyUpgrade: vi.fn(),
  requestCompanyUpgrade: vi.fn(),
}));

const candidate = {
  scope: "project",
  zone: "asset",
  assetStatus: "active" as const,
  projectId: "project-a",
};

describe("project company publication eligibility", () => {
  it("requires a current preview before submitting an edited publication", async () => {
    vi.mocked(fetchNamingOptions).mockResolvedValue({
      required: true,
      rule_version: 12,
      directories: [
        {
          directory_key: "company.methodology",
          scope: "company",
          display_name: "方法论",
          default_confidentiality: "L2",
          enabled: true,
          sort_order: 1,
        },
      ],
      default_confidentiality: "L2",
      message: null,
    });
    let completeOld!: (value: NamingPreviewDTO) => void;
    const old = new Promise<NamingPreviewDTO>((resolve) => {
      completeOld = resolve;
    });
    const result = (name: string): NamingPreviewDTO => ({
      required: true,
      canonical_name: name,
      rule_version: 12,
      fields: {},
      notices: [],
      message: null,
    });
    vi.mocked(previewCompanyUpgrade)
      .mockReset()
      .mockReturnValueOnce(old)
      .mockResolvedValueOnce(result("当前发布文件名.md"));
    vi.mocked(requestCompanyUpgrade).mockReset();
    const onSubmitted = vi.fn();
    render(
      <ProjectCompanyPublicationDialog
        projectId="project-a"
        target={{ id: "asset-a", title: "旧主题" }}
        onClose={() => undefined}
        onSubmitted={onSubmitted}
      />,
    );
    await screen.findByRole("combobox", { name: "正式目录" });
    fireEvent.change(screen.getByLabelText("适用对象"), { target: { value: "全公司" } });
    fireEvent.click(screen.getByRole("button", { name: "预览目标文件名" }));
    fireEvent.change(screen.getByLabelText("主题"), { target: { value: "新主题" } });
    await act(async () => completeOld(result("旧发布文件名.md")));
    fireEvent.click(screen.getByRole("button", { name: "提交公司发布申请" }));
    expect(screen.getByRole("alert")).toHaveTextContent("请先预览并确认目标文件名");
    expect(requestCompanyUpgrade).not.toHaveBeenCalled();
    expect(onSubmitted).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "预览目标文件名" }));
    await screen.findByText("当前发布文件名.md");
    fireEvent.click(screen.getByRole("button", { name: "提交公司发布申请" }));
    await waitFor(() => expect(onSubmitted).toHaveBeenCalledTimes(1));
    expect(requestCompanyUpgrade).toHaveBeenCalledTimes(1);
    expect(requestCompanyUpgrade).toHaveBeenCalledWith(
      "project-a",
      "asset-a",
      expect.objectContaining({
        naming: expect.objectContaining({
          subject: "新主题",
          subject_is_manual: true,
          applicable_to: "全公司",
        }),
      }),
    );
  });

  it("uses the reviewed publication subject instead of wrapping the source filename", () => {
    expect(createPublicationNamingValue("验收发布主题").naming).toEqual(
      expect.objectContaining({ subject: "验收发布主题", subject_is_manual: true }),
    );
  });
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
