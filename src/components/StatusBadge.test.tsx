import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import StatusBadge from "./StatusBadge";

describe("StatusBadge", () => {
  it("renders the label inside the status-pill base class", () => {
    render(<StatusBadge label="已通过" />);
    const el = screen.getByText("已通过");
    expect(el).toBeInTheDocument();
    expect(el).toHaveClass("status-pill");
  });

  it("appends the variant modifier class", () => {
    render(<StatusBadge label="失败" variant="ig-status-failed" />);
    const el = screen.getByText("失败");
    expect(el).toHaveClass("status-pill");
    expect(el).toHaveClass("ig-status-failed");
  });

  it("sets the title attribute when provided", () => {
    render(<StatusBadge label="索引中" title="检索索引状态" />);
    expect(screen.getByText("索引中")).toHaveAttribute("title", "检索索引状态");
  });

  it("maps semantic tone to the shared visual contract", () => {
    render(<StatusBadge label="已启用" tone="success" />);
    expect(screen.getByText("已启用")).toHaveClass("status-pill", "is-success");
  });

  it("derives one icon, label, tone, and guidance from an operation status", () => {
    render(<StatusBadge status="submitted" />);
    const badge = screen.getByText("已提交");
    expect(badge).toHaveClass("status-pill", "is-info");
    expect(badge).toHaveAttribute("data-operation-status", "submitted");
    expect(badge).toHaveAttribute("title", "系统已受理请求，但作业尚未完成。");
    expect(badge.querySelector("svg")).toBeInTheDocument();
  });

  it("keeps submitted, processing, and completed as distinct user-visible states", () => {
    const { rerender } = render(<StatusBadge status="submitted" />);
    expect(screen.getByText("已提交")).toBeInTheDocument();
    rerender(<StatusBadge status="processing" />);
    expect(screen.getByText("处理中")).toBeInTheDocument();
    rerender(<StatusBadge status="completed" />);
    expect(screen.getByText("已完成")).toBeInTheDocument();
  });
});
