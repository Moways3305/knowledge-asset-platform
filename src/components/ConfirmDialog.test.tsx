import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import ConfirmDialog from "./ConfirmDialog";

describe("ConfirmDialog", () => {
  it("关闭时不渲染", () => {
    const { container } = render(
      <ConfirmDialog open={false} title="删除？" onConfirm={() => {}} onCancel={() => {}} />,
    );
    expect(container.firstChild).toBeNull();
  });

  it("打开后展示动作图形并优先聚焦取消按钮", () => {
    const { container } = render(
      <ConfirmDialog
        open
        title="删除资产？"
        description="此操作保留审计记录"
        danger
        onConfirm={() => {}}
        onCancel={() => {}}
      />,
    );
    expect(screen.getByRole("dialog", { name: "删除资产？" })).toBeInTheDocument();
    expect(container.querySelector(".confirm-dialog-icon svg")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "取消" })).toHaveFocus();
  });

  it("确认、取消和 Escape 均遵循原有交互", () => {
    const onConfirm = vi.fn();
    const onCancel = vi.fn();
    render(
      <ConfirmDialog
        open
        title="确认动作"
        confirmText="确认执行"
        onConfirm={onConfirm}
        onCancel={onCancel}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "确认执行" }));
    fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });
    expect(onConfirm).toHaveBeenCalledTimes(1);
    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it("忙碌时禁用按钮且 Escape 不关闭", () => {
    const onCancel = vi.fn();
    render(
      <ConfirmDialog
        open
        title="处理中"
        busy
        busyText="删除中…"
        onConfirm={() => {}}
        onCancel={onCancel}
      />,
    );
    expect(screen.getByRole("button", { name: "删除中…" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "取消" })).toBeDisabled();
    fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });
    expect(onCancel).not.toHaveBeenCalled();
  });

  it("错误态只展示安全文案", () => {
    render(
      <ConfirmDialog
        open
        title="确认动作"
        error="POST /internal failed token=secret"
        onConfirm={() => {}}
        onCancel={() => {}}
      />,
    );
    expect(screen.getByText("操作未完成，请检查后重试。")).toBeInTheDocument();
    expect(screen.queryByText(/token=secret/i)).not.toBeInTheDocument();
  });
});
