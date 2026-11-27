import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, useLocation, useNavigate } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import UploadPage from "./UploadPage";

const flow = vi.hoisted(() => ({
  current: {
    activePath: "b",
    switchPath: vi.fn(),
    handleReset: vi.fn(),
    handleDeletePending: vi.fn().mockResolvedValue(undefined),
    confirmReady: false,
    confirmSubmitted: false,
    awaitingProjectReview: false,
    taskId: "test-task-id",
    pendingTasks: [] as Array<{ id: string }>,
    pendingLoading: false,
    pendingError: null as string | null,
    localPendingTasks: [] as Array<{ id: string }>,
    localPendingLoading: false,
    localPendingError: null as string | null,
    handleSelectPendingTask: vi.fn(),
    loadPending: vi.fn(),
    projects: [] as Array<{ projectId: string; projectName: string }>,
    targetLibrary: "",
    targetLocked: false,
    setTargetLibrary: vi.fn(),
    setTargetProjectId: vi.fn(),
  },
}));

vi.mock("./upload/useUploadFlow", () => ({ useUploadFlow: () => flow.current }));
vi.mock("../components/MyUploadsPanel", () => ({ default: () => <div>本人上传记录列表</div> }));
vi.mock("./upload/UploadStepA", () => ({ default: () => <div>企微待确认列表</div> }));
vi.mock("./upload/UploadStepB", () => ({ default: () => <div>本地文件上传区</div> }));
vi.mock("./upload/UploadConfirmPanel", () => ({
  default: ({ onExit, onReject }: { onExit: () => void; onReject: () => void }) => (
    <div>
      已提交，等待项目经理确认
      <button onClick={onExit}>退出</button>
      <button onClick={onReject}>拒绝入库</button>
    </div>
  ),
}));

function renderPage(entry = "/upload") {
  return render(
    <MemoryRouter initialEntries={[entry]}>
      <UploadPage />
      <NavigationProbe />
    </MemoryRouter>,
  );
}

function NavigationProbe() {
  const location = useLocation();
  const navigate = useNavigate();
  return (
    <>
      <output aria-label="上传路径">{location.search}</output>
      <button onClick={() => navigate(-1)}>浏览器后退</button>
    </>
  );
}

describe("UploadPage reference workflow", () => {
  beforeEach(() => {
    flow.current.activePath = "b";
    flow.current.pendingTasks = [];
    flow.current.pendingLoading = false;
    flow.current.pendingError = null;
    flow.current.localPendingTasks = [];
    flow.current.localPendingLoading = false;
    flow.current.localPendingError = null;
    flow.current.handleSelectPendingTask.mockReset();
    flow.current.confirmReady = false;
    flow.current.confirmSubmitted = false;
    flow.current.awaitingProjectReview = false;
    flow.current.projects = [];
    flow.current.targetLibrary = "";
    flow.current.targetLocked = false;
    flow.current.setTargetLibrary.mockReset();
    flow.current.setTargetProjectId.mockReset();
    flow.current.switchPath.mockReset();
    flow.current.handleReset.mockReset();
    flow.current.handleDeletePending.mockReset();
    flow.current.handleDeletePending.mockResolvedValue(undefined);
    window.history.replaceState({ idx: 0 }, "");
  });

  it("resumes a local upload by exact task rather than the notification source hint", () => {
    const localTask = { id: "local-target" };
    flow.current.localPendingTasks = [localTask];
    renderPage("/upload?task_id=local-target&source=wecom");
    expect(flow.current.handleSelectPendingTask).toHaveBeenCalledExactlyOnceWith(localTask);
    expect(flow.current.switchPath).not.toHaveBeenCalled();
    expect(screen.getByLabelText("上传路径")).toHaveTextContent("source=local");
  });

  it("switches to an imported task's actual source before resuming it", () => {
    const importedTask = { id: "imported-target" };
    flow.current.pendingTasks = [importedTask];
    const entry = "/upload?task_id=imported-target&source=local";
    const view = renderPage(entry);
    expect(flow.current.switchPath).toHaveBeenCalledWith("a");
    expect(flow.current.handleSelectPendingTask).not.toHaveBeenCalled();
    flow.current.activePath = "a";
    view.rerender(
      <MemoryRouter initialEntries={[entry]}>
        <UploadPage />
        <NavigationProbe />
      </MemoryRouter>,
    );
    expect(flow.current.handleSelectPendingTask).toHaveBeenCalledExactlyOnceWith(importedTask);
    expect(screen.getByLabelText("上传路径")).toHaveTextContent("source=wecom");
  });

  it("waits for both authorized source lists before treating a reminder as historical", () => {
    flow.current.pendingLoading = true;
    renderPage("/upload?task_id=import-still-loading");
    expect(screen.getByRole("heading", { name: "上传资料" })).toBeInTheDocument();
    expect(screen.getByLabelText("上传路径")).not.toHaveTextContent("view=history");
  });

  it("resolves a stale processing reminder in exact history instead of a blank upload", () => {
    renderPage("/upload?source=local&task_id=finished-task");
    expect(screen.getByRole("heading", { name: "上传记录" })).toBeInTheDocument();
    expect(screen.getByLabelText("上传路径")).toHaveTextContent("task_id=finished-task");
    expect(screen.getByLabelText("上传路径")).toHaveTextContent("view=history");
    expect(flow.current.handleSelectPendingTask).not.toHaveBeenCalled();
  });

  it("does not resume a pending confirmation behind an explicitly opened historical record", () => {
    flow.current.localPendingTasks = [{ id: "target-task" }];
    renderPage("/upload?view=history&task_id=target-task");
    expect(screen.getByRole("heading", { name: "上传记录" })).toBeInTheDocument();
    expect(flow.current.handleSelectPendingTask).not.toHaveBeenCalled();
  });

  it("returns a project upload deep link to its project and keeps a personal entry after changing tabs", () => {
    flow.current.projects = [{ projectId: "p1", projectName: "项目一" }];
    const view = renderPage("/upload?source=local&project_id=p1");
    expect(screen.getByRole("link", { name: "返回项目知识库" })).toHaveAttribute(
      "href",
      "/project/p1/knowledge",
    );
    view.unmount();
    render(
      <MemoryRouter
        initialEntries={[
          {
            pathname: "/upload",
            search: "?source=local",
            state: {
              backTo: "/my/knowledge?keyword=复盘&page=3",
              backLabel: "返回个人知识",
              source: "personal",
            },
          },
        ]}
      >
        <UploadPage />
      </MemoryRouter>,
    );
    fireEvent.click(screen.getByRole("button", { name: "上传记录" }));
    expect(screen.getByRole("link", { name: "返回个人知识" })).toHaveAttribute(
      "href",
      "/my/knowledge?keyword=复盘&page=3",
    );
    fireEvent.click(screen.getByRole("button", { name: "上传" }));
    expect(screen.getByRole("link", { name: "返回个人知识" })).toHaveAttribute(
      "href",
      "/my/knowledge?keyword=复盘&page=3",
    );
  });

  it("starts with the local upload workspace and switches source through the flow", () => {
    flow.current.pendingTasks = [{ id: "historical-import" }];
    renderPage();

    expect(screen.getByRole("heading", { name: "上传资料" })).toBeInTheDocument();
    expect(screen.getByText("本地文件上传区")).toBeInTheDocument();
    expect(screen.queryByText("企微待确认列表")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "历史导入待确认" }));
    expect(flow.current.switchPath).toHaveBeenCalledWith("a");
  });

  it("shows no retired scan or history entry when there are no imported tasks", () => {
    renderPage();
    expect(screen.getByText("本地文件上传区")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "历史导入待确认" })).not.toBeInTheDocument();
    expect(screen.queryByText(/微盘扫描|企微微盘/)).not.toBeInTheDocument();
  });

  it("returns to upload history from a detail link and keeps the source through tab and browser navigation", () => {
    renderPage("/upload?view=history&source=local&project_id=p1");
    expect(screen.getByRole("heading", { name: "上传记录" })).toBeInTheDocument();
    expect(screen.getByText("本人上传记录列表")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "上传" }));
    expect(screen.getByLabelText("上传路径")).toHaveTextContent("?source=local&project_id=p1");
    expect(screen.getByRole("heading", { name: "上传资料" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "浏览器后退" }));
    expect(screen.getByRole("heading", { name: "上传记录" })).toBeInTheDocument();
    expect(screen.getByLabelText("上传路径")).toHaveTextContent("view=history");
  });

  it("prefills a permitted project only for a new unlocked confirmation", () => {
    flow.current.projects = [{ projectId: "allowed", projectName: "当前项目" }];
    flow.current.confirmReady = true;
    renderPage("/upload?project_id=allowed&source=local");
    expect(flow.current.setTargetLibrary).toHaveBeenCalledWith("project");
    expect(flow.current.setTargetProjectId).toHaveBeenCalledWith("allowed");
  });

  it.each(["unavailable", "locked", "selected"])(
    "preserves the target when the project context is %s",
    (condition) => {
      flow.current.projects =
        condition === "unavailable" ? [] : [{ projectId: "allowed", projectName: "当前项目" }];
      flow.current.confirmReady = true;
      flow.current.targetLocked = condition === "locked";
      flow.current.targetLibrary = condition === "selected" ? "personal" : "";
      renderPage("/upload?project_id=allowed&source=local");
      expect(flow.current.setTargetLibrary).not.toHaveBeenCalled();
      expect(flow.current.setTargetProjectId).not.toHaveBeenCalled();
    },
  );

  it("does not present a pending project submission as already in the knowledge base", () => {
    flow.current.confirmSubmitted = true;
    flow.current.awaitingProjectReview = true;
    renderPage();

    expect(screen.getByText("已提交，等待项目经理确认")).toBeInTheDocument();
    expect(screen.queryByText("已进入知识库")).not.toBeInTheDocument();
  });

  it("returns a local confirmation to its local pending list", () => {
    flow.current.confirmReady = true;
    renderPage();

    fireEvent.click(screen.getByRole("button", { name: "退出" }));
    expect(flow.current.handleReset).toHaveBeenCalledTimes(1);
    expect(flow.current.switchPath).toHaveBeenCalledWith("b");
  });

  it("rejects a confirmation and deletes the pending task", async () => {
    flow.current.confirmReady = true;
    renderPage();

    fireEvent.click(screen.getByRole("button", { name: "拒绝入库" }));
    // 需要等待异步删除完成
    await vi.waitFor(() => {
      expect(flow.current.handleDeletePending).toHaveBeenCalledWith("test-task-id");
    });
    expect(flow.current.handleReset).not.toHaveBeenCalled();
    expect(flow.current.switchPath).not.toHaveBeenCalled();
  });

  it("keeps the confirmation open when permanent rejection fails", async () => {
    flow.current.confirmReady = true;
    flow.current.handleDeletePending.mockRejectedValueOnce(new Error("network"));
    renderPage();

    fireEvent.click(screen.getByRole("button", { name: "拒绝入库" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("拒绝入库失败");
    expect(flow.current.handleReset).not.toHaveBeenCalled();
    expect(flow.current.switchPath).not.toHaveBeenCalled();
    expect(screen.getByText("已提交，等待项目经理确认")).toBeInTheDocument();
  });
});
