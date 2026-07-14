import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import UploadPage from "./UploadPage";

const flow = vi.hoisted(() => ({
  current: {
    activePath: "b",
    switchPath: vi.fn(),
    confirmReady: false,
    confirmSubmitted: true,
    awaitingProjectReview: true,
    flowState: "submitted",
    naming: null,
  },
}));

vi.mock("./upload/useUploadFlow", () => ({ useUploadFlow: () => flow.current }));
vi.mock("./upload/UploadStepA", () => ({ default: () => null }));
vi.mock("./upload/UploadStepB", () => ({ default: () => null }));
vi.mock("./upload/UploadNamingCard", () => ({ default: () => null }));
vi.mock("./upload/UploadConfirmPanel", () => ({
  default: () => <div>已提交，待项目经理确认</div>,
}));

describe("UploadPage project approval progress", () => {
  it("does not present a pending project submission as already in the knowledge base", () => {
    render(
      <MemoryRouter>
        <UploadPage />
      </MemoryRouter>,
    );
    const approvalStep = screen.getByText("项目审批").closest("li");
    expect(approvalStep).toHaveClass("is-active");
    expect(approvalStep).not.toHaveClass("is-done");
    expect(screen.getByText("已提交，待项目经理确认")).toBeInTheDocument();
  });
});
