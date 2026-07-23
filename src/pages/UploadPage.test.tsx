import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import UploadPage from "./UploadPage";

const flow = vi.hoisted(() => ({
  current: {
    activePath: "b",
    switchPath: vi.fn(),
    handleReset: vi.fn(),
    confirmReady: false,
    confirmSubmitted: false,
    awaitingProjectReview: false,
  },
}));

vi.mock("./upload/useUploadFlow", () => ({ useUploadFlow: () => flow.current }));
vi.mock("./upload/UploadStepA", () => ({ default: () => <div>企微待确认列表</div> }));
vi.mock("./upload/UploadStepB", () => ({ default: () => <div>本地文件上传区</div> }));
vi.mock("./upload/UploadConfirmPanel", () => ({
  default: ({ onCancel }: { onCancel: () => void }) => (
    <div>
      已提交，等待项目经理确认
      <button onClick={onCancel}>取消确认</button>
    </div>
  ),
}));

function renderPage() {
  return render(
    <MemoryRouter>
      <UploadPage />
    </MemoryRouter>,
  );
}

describe("UploadPage reference workflow", () => {
  beforeEach(() => {
    flow.current.activePath = "b";
    flow.current.confirmReady = false;
    flow.current.confirmSubmitted = false;
    flow.current.awaitingProjectReview = false;
    flow.current.switchPath.mockReset();
    flow.current.handleReset.mockReset();
    window.history.replaceState({ idx: 0 }, "");
  });

  it("starts with the local upload workspace and switches source through the flow", () => {
    renderPage();

    expect(screen.getByRole("heading", { name: "上传与入库" })).toBeInTheDocument();
    expect(screen.getByText("本地文件上传区")).toBeInTheDocument();
    expect(screen.queryByText("企微待确认列表")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "企微微盘待确认" }));
    expect(flow.current.switchPath).toHaveBeenCalledWith("a");
  });

  it("does not present a pending project submission as already in the knowledge base", () => {
    flow.current.confirmSubmitted = true;
    flow.current.awaitingProjectReview = true;
    renderPage();

    expect(screen.getByText("已提交，等待项目经理确认")).toBeInTheDocument();
    expect(screen.queryByText("已进入知识库")).not.toBeInTheDocument();
  });

  it("returns a directly opened confirmation to the real pending list", () => {
    flow.current.confirmReady = true;
    renderPage();

    fireEvent.click(screen.getByRole("button", { name: "取消确认" }));
    expect(flow.current.switchPath).toHaveBeenCalledWith("a");
  });

  it("uses browser history when the confirmation has a previous page", () => {
    window.history.replaceState({ idx: 1 }, "");
    flow.current.confirmReady = true;
    renderPage();

    fireEvent.click(screen.getByRole("button", { name: "取消确认" }));
    expect(flow.current.handleReset).toHaveBeenCalledTimes(1);
    expect(flow.current.switchPath).not.toHaveBeenCalled();
  });
});
