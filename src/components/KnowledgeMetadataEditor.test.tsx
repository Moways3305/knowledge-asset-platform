import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import KnowledgeMetadataEditor from "./KnowledgeMetadataEditor";
import {
  fetchKnowledgeDetail,
  fetchKnowledgeDirectories,
  updateKnowledgeMetadata,
} from "../api/knowledge";
import type { KnowledgeDetailVM } from "../types/knowledge";

vi.mock("../api/knowledge", () => ({
  fetchKnowledgeDetail: vi.fn(),
  fetchKnowledgeDirectories: vi.fn(),
  updateKnowledgeMetadata: vi.fn(),
}));
const asset = {
  id: "asset-1",
  title: "公司资料",
  scope: "company",
  tags: ["制度"],
  confidentialityLevel: "L2",
  directoryKey: "company.methodology",
  directoryPath: "公司库 / 方法论",
  projectId: null,
  metadataUpdatedAt: "2026-09-29T01:00:00.123456Z",
  access: { canEditMetadata: true },
} as KnowledgeDetailVM;

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(fetchKnowledgeDetail).mockResolvedValue(asset);
  vi.mocked(fetchKnowledgeDirectories).mockResolvedValue([]);
  vi.mocked(updateKnowledgeMetadata).mockResolvedValue({
    asset_id: asset.id,
    updated_at: "2026-09-29T02:00:00Z",
  });
});

async function open(onSaved = vi.fn()) {
  render(<KnowledgeMetadataEditor asset={asset} onSaved={onSaved} />);
  fireEvent.click(screen.getByRole("button", { name: "编辑资料" }));
  await screen.findByRole("dialog");
  await waitFor(() => expect(fetchKnowledgeDirectories).toHaveBeenCalled());
  return onSaved;
}

describe("资料编辑", () => {
  it("没有后端授权不显示入口", () => {
    render(
      <KnowledgeMetadataEditor
        asset={{ ...asset, access: { ...asset.access, canEditMetadata: false } }}
        onSaved={vi.fn()}
      />,
    );
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
  it("打开时读取最新详情，保存只发送修改字段和精确时间", async () => {
    const onSaved = await open();
    fireEvent.change(screen.getByLabelText("资料标题"), { target: { value: "修正标题" } });
    fireEvent.change(screen.getByLabelText("修改原因"), { target: { value: "核对原文件后纠错" } });
    fireEvent.click(screen.getByRole("button", { name: "保存修改" }));
    await waitFor(() => expect(onSaved).toHaveBeenCalledOnce());
    expect(updateKnowledgeMetadata).toHaveBeenCalledWith(asset.id, {
      title: "修正标题",
      expected_updated_at: asset.metadataUpdatedAt,
      reason: "核对原文件后纠错",
      confirm_downgrade: false,
    });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
  it("降低等级必须额外确认，切换等级会重置确认", async () => {
    await open();
    fireEvent.change(screen.getByLabelText("修改原因"), { target: { value: "公开资料误标" } });
    fireEvent.change(screen.getByLabelText("保密等级"), { target: { value: "L1" } });
    expect(screen.getByRole("button", { name: "保存修改" })).toBeDisabled();
    fireEvent.click(screen.getByRole("checkbox"));
    expect(screen.getByRole("button", { name: "保存修改" })).toBeEnabled();
    fireEvent.change(screen.getByLabelText("保密等级"), { target: { value: "L3" } });
    fireEvent.change(screen.getByLabelText("保密等级"), { target: { value: "L1" } });
    expect(screen.getByRole("checkbox")).not.toBeChecked();
  });
  it("冲突后保留用户输入，不声称保存成功", async () => {
    vi.mocked(updateKnowledgeMetadata).mockRejectedValue(
      new Error("资料已被更新，请刷新后重新编辑"),
    );
    const onSaved = await open();
    fireEvent.change(screen.getByLabelText("资料标题"), { target: { value: "我的修改" } });
    fireEvent.change(screen.getByLabelText("修改原因"), { target: { value: "纠错" } });
    fireEvent.click(screen.getByRole("button", { name: "保存修改" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("资料已被更新");
    expect(screen.getByLabelText("资料标题")).toHaveValue("我的修改");
    expect(onSaved).not.toHaveBeenCalled();
  });
  it("目录加载失败不阻止其它信息编辑", async () => {
    vi.mocked(fetchKnowledgeDirectories).mockRejectedValue(new Error("offline"));
    await open();
    await screen.findByText(/目录加载失败/);
    expect(screen.getByLabelText("正式目录")).toBeDisabled();
    expect(screen.getByLabelText("资料标题")).toBeEnabled();
  });
  it("取消不提交修改", async () => {
    await open();
    fireEvent.click(screen.getByRole("button", { name: "取消" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(updateKnowledgeMetadata).not.toHaveBeenCalled();
  });
});
