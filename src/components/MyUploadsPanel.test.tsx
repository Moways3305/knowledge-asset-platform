import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import MyUploadsPanel from "./MyUploadsPanel";

const ingestApi = vi.hoisted(() => ({ fetchMyUploads: vi.fn() }));
vi.mock("../api/ingest", () => ingestApi);

describe("MyUploadsPanel", () => {
  beforeEach(() => ingestApi.fetchMyUploads.mockReset());

  it("shows rejected history and its review comment without claiming ongoing processing", async () => {
    ingestApi.fetchMyUploads.mockResolvedValue([
      {
        task_id: "rejected",
        source_file_name: "拒绝资料.md",
        uploaded_at: "2026-10-29T01:00:00Z",
        processing_status: "rejected",
        final_status: "rejected",
        review_comment: "请补充依据",
        duplicate_result: "none",
        result_asset_id: null,
      },
    ]);
    render(
      <MemoryRouter>
        <MyUploadsPanel onClose={vi.fn()} />
      </MemoryRouter>,
    );
    expect(await screen.findByText("拒绝资料.md")).toBeInTheDocument();
    expect(
      screen.getAllByText("审核已拒绝").filter((element) => element.tagName === "DD"),
    ).toHaveLength(1);
    expect(document.querySelector(".my-upload-final-status")).toHaveTextContent("审核已拒绝");
    expect(screen.getByText(/请补充依据/)).toBeInTheDocument();
    expect(screen.queryByText("状态更新中")).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "修改后重新上传" })).toHaveAttribute("href", "/upload");
    fireEvent.change(screen.getByLabelText("最终状态"), { target: { value: "rejected" } });
    await waitFor(() =>
      expect(ingestApi.fetchMyUploads).toHaveBeenLastCalledWith(
        expect.objectContaining({ finalStatus: "rejected" }),
      ),
    );
  });

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

  it("renders and filters cancelled uploads as a terminal state", async () => {
    ingestApi.fetchMyUploads.mockResolvedValue([
      {
        task_id: "task-cancelled",
        source_file_name: "已取消资料.pdf",
        source_file_size: 1024,
        uploaded_at: "2026-09-04T08:00:00Z",
        target_scope: "project",
        target_project_id: "project-1",
        target_project_name: "项目 A",
        processing_status: "cancelled",
        final_status: "cancelled",
        duplicate_result: "none",
        result_asset_id: null,
      },
    ]);
    render(
      <MemoryRouter>
        <MyUploadsPanel onClose={vi.fn()} />
      </MemoryRouter>,
    );

    expect(await screen.findByText("已取消资料.pdf")).toBeInTheDocument();
    expect(
      screen.getAllByText("已取消").filter((element) => element.tagName === "DD"),
    ).toHaveLength(1);
    expect(document.querySelector(".my-upload-final-status")).toHaveTextContent("已取消");
    fireEvent.change(screen.getByLabelText("最终状态"), { target: { value: "cancelled" } });
    await waitFor(() =>
      expect(ingestApi.fetchMyUploads).toHaveBeenLastCalledWith(
        expect.objectContaining({ finalStatus: "cancelled" }),
      ),
    );
  });
});
