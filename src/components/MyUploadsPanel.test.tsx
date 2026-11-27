import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import MyUploadsPanel from "./MyUploadsPanel";

const ingestApi = vi.hoisted(() => ({ fetchMyUploads: vi.fn() }));
vi.mock("../api/ingest", () => ingestApi);

function UploadHistoryNavigation() {
  const location = useLocation();
  const navigate = useNavigate();
  return (
    <>
      <output aria-label="历史返回来源">{JSON.stringify(location.state)}</output>
      <button onClick={() => navigate(-1)}>浏览器后退</button>
    </>
  );
}

describe("MyUploadsPanel", () => {
  beforeEach(() => {
    ingestApi.fetchMyUploads.mockReset();
  });

  it("locates an exact historical task and restores it after reading its asset", async () => {
    const taskId = "00000000-0000-0000-0000-000000000099";
    const entry = `/upload?view=history&task_id=${taskId}&source=local&project_id=p1`;
    ingestApi.fetchMyUploads.mockResolvedValue([
      {
        task_id: taskId,
        source_file_name: "旧资料.pdf",
        uploaded_at: "2026-08-26T08:00:00Z",
        processing_status: "completed",
        final_status: "completed",
        duplicate_result: "none",
        result_asset_id: "asset-1",
      },
    ]);
    render(
      <MemoryRouter initialEntries={[entry]}>
        <UploadHistoryNavigation />
        <Routes>
          <Route path="/upload" element={<MyUploadsPanel onClose={vi.fn()} />} />
          <Route path="/knowledge/:id" element={<div>资产详情</div>} />
        </Routes>
      </MemoryRouter>,
    );
    expect(await screen.findByText("旧资料.pdf")).toBeInTheDocument();
    expect(ingestApi.fetchMyUploads).toHaveBeenLastCalledWith({ taskId });
    expect(screen.getByText("处理详情").closest("details")).toHaveAttribute("open");
    fireEvent.click(screen.getByRole("link", { name: "查看资产详情" }));
    expect(screen.getByLabelText("历史返回来源")).toHaveTextContent(entry);
    fireEvent.click(screen.getByRole("button", { name: "浏览器后退" }));
    expect(await screen.findByText("旧资料.pdf")).toBeInTheDocument();
    expect(ingestApi.fetchMyUploads).toHaveBeenLastCalledWith({ taskId });
    fireEvent.click(screen.getByRole("button", { name: "查看全部上传记录" }));
    await waitFor(() =>
      expect(ingestApi.fetchMyUploads).toHaveBeenLastCalledWith(
        expect.objectContaining({ finalStatus: undefined }),
      ),
    );
    expect(screen.queryByText("正在查看这条上传记录。")).not.toBeInTheDocument();
  });

  it("explains an inaccessible target and preserves applied upload filters through browser history", async () => {
    ingestApi.fetchMyUploads.mockResolvedValue([]);
    render(
      <MemoryRouter initialEntries={["/upload?view=history&task_id=missing&upload_status=failed"]}>
        <MyUploadsPanel onClose={vi.fn()} />
        <UploadHistoryNavigation />
      </MemoryRouter>,
    );
    expect(await screen.findByText("该上传记录不存在或当前账号无权查看。")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("最终状态"), { target: { value: "completed" } });
    await waitFor(() =>
      expect(ingestApi.fetchMyUploads).toHaveBeenLastCalledWith(
        expect.objectContaining({ finalStatus: "completed" }),
      ),
    );
    fireEvent.click(screen.getByRole("button", { name: "浏览器后退" }));
    await waitFor(() =>
      expect(ingestApi.fetchMyUploads).toHaveBeenLastCalledWith({ taskId: "missing" }),
    );
    expect(screen.getByLabelText("最终状态")).toHaveValue("failed");
  });

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
    expect(screen.getByRole("link", { name: "修改后重新上传" })).toHaveAttribute(
      "href",
      "/upload?source=local",
    );
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
