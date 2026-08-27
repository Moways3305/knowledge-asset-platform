import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import MyUploadsPanel from "./MyUploadsPanel";

const ingestApi = vi.hoisted(() => ({ fetchMyUploads: vi.fn() }));
vi.mock("../api/ingest", () => ingestApi);

describe("MyUploadsPanel", () => {
  beforeEach(() => ingestApi.fetchMyUploads.mockReset());

  it("shows separate processing, final, duplicate and permitted project facts", async () => {
    ingestApi.fetchMyUploads.mockResolvedValue([
      {
        task_id: "task-1",
        source_file_name: "交付方案.pdf",
        source_file_size: 2048,
        uploaded_at: "2026-08-26T08:00:00Z",
        target_scope: "project",
        target_project_id: "project-1",
        target_project_name: "项目 A",
        processing_status: "completed",
        final_status: "completed",
        duplicate_result: "independent",
        result_asset_id: "asset-1",
      },
    ]);
    render(
      <MemoryRouter>
        <MyUploadsPanel onClose={vi.fn()} />
      </MemoryRouter>,
    );

    expect(await screen.findByText("交付方案.pdf")).toBeInTheDocument();
    expect(screen.getByText("项目库 · 项目 A")).toBeInTheDocument();
    expect(screen.getByText("处理完成")).toBeInTheDocument();
    expect(screen.getAllByText("已完成")).toHaveLength(2);
    expect(screen.getByText("作为独立资料入库")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "查看资产详情" })).toHaveAttribute(
      "href",
      "/knowledge/asset-1",
    );
  });

  it("distinguishes never-uploaded and filtered empty states", async () => {
    ingestApi.fetchMyUploads.mockResolvedValue([]);
    render(
      <MemoryRouter>
        <MyUploadsPanel onClose={vi.fn()} />
      </MemoryRouter>,
    );
    expect(await screen.findByText("尚未上传资料")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("最终状态"), {
      target: { value: "duplicate_skipped" },
    });
    await waitFor(() => expect(ingestApi.fetchMyUploads).toHaveBeenCalledTimes(2));
    expect(screen.getByText("当前筛选无结果")).toBeInTheDocument();
  });
});
