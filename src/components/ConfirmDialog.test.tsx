import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import ConfirmDialog from "./ConfirmDialog";

describe("ConfirmDialog", () => {
  it("renders nothing when closed", () => {
    const { container } = render(
      <ConfirmDialog open={false} title="删除？" onConfirm={() => {}} onCancel={() => {}} />
    );
    expect(container.firstChild).toBeNull();
  });

  it("renders title, description and default actions when open", () => {
    render(
      <ConfirmDialog open title="删除资产？" description="此操作保留审计" onConfirm={() => {}} onCancel={() => {}} />
    );
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText("删除资产？")).toBeInTheDocument();
    expect(screen.getByText("此操作保留审计")).toBeInTheDocument();
    expect(screen.getByText("确认")).toBeInTheDocument();
    expect(screen.getByText("取消")).toBeInTheDocument();
  });

  it("calls onConfirm / onCancel from the action buttons", () => {
    const onConfirm = vi.fn();
    const onCancel = vi.fn();
    render(<ConfirmDialog open title="t" confirmText="确认删除" onConfirm={onConfirm} onCancel={onCancel} />);
    fireEvent.click(screen.getByText("确认删除"));
    fireEvent.click(screen.getByText("取消"));
    expect(onConfirm).toHaveBeenCalledTimes(1);
    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it("disables buttons and shows busyText while busy", () => {
    render(<ConfirmDialog open title="t" busy busyText="删除中…" onConfirm={() => {}} onCancel={() => {}} />);
    const confirmBtn = screen.getByText("删除中…");
    expect(confirmBtn).toBeDisabled();
    expect(screen.getByText("取消")).toBeDisabled();
  });

  it("shows the error message when provided", () => {
    render(<ConfirmDialog open title="t" error="创建失败" onConfirm={() => {}} onCancel={() => {}} />);
    expect(screen.getByText("创建失败")).toBeInTheDocument();
  });
});
