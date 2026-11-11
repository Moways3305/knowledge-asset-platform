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
