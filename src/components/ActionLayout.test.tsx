import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { MemoryRouter, Link, useLocation } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { ActionMenu } from "./ActionLayout";
import Button from "./Button";
import TaskModal from "./TaskModal";

describe("ActionMenu", () => {
  it("keeps a short visible label while naming the affected record", () => {
    render(
      <ActionMenu ariaLabel="验收资料的更多操作">
        <Button>查看记录</Button>
      </ActionMenu>,
    );
    expect(screen.getByRole("button", { name: "验收资料的更多操作" })).toHaveTextContent(
      "更多操作",
    );
  });

  it("returns to the page's Tab order after the last portaled action", async () => {
    const user = userEvent.setup();
    render(
      <>
        <ActionMenu>
          <Button>第一项</Button>
          <Button>最后一项</Button>
        </ActionMenu>
        <button>下一个页面操作</button>
      </>,
    );
    await user.click(screen.getByRole("button", { name: "更多操作" }));
    await user.tab();
    expect(screen.getByRole("button", { name: "最后一项" })).toHaveFocus();
    await user.tab();
    expect(screen.getByRole("button", { name: "下一个页面操作" })).toHaveFocus();
    expect(screen.queryByRole("button", { name: "最后一项" })).not.toBeInTheDocument();
  });
  it("opens from the keyboard, focuses an available action and restores focus on Escape", async () => {
    const user = userEvent.setup();
    const outerKeyDown = vi.fn();
    render(
      <div onKeyDown={outerKeyDown}>
        <ActionMenu>
          <Button disabled>不可用操作</Button>
          <Button>导出摘要</Button>
        </ActionMenu>
      </div>,
    );
    const trigger = screen.getByRole("button", { name: "更多操作" });
    trigger.focus();
    await user.keyboard("{ArrowDown}");
    expect(screen.getByRole("button", { name: "导出摘要" })).toHaveFocus();
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    outerKeyDown.mockClear();

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("button", { name: "导出摘要" })).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    // Escape closes only this disclosure, not its containing dialog.
    expect(outerKeyDown).not.toHaveBeenCalled();
  });

  it("runs a selected action once, closes the panel and returns to the trigger", async () => {
    const user = userEvent.setup();
    const onClick = vi.fn();
    render(
      <ActionMenu label="资料操作">
        <Button onClick={onClick}>复制摘要</Button>
      </ActionMenu>,
    );
    const trigger = screen.getByRole("button", { name: "资料操作" });
    await user.click(trigger);
    await user.click(screen.getByRole("button", { name: "复制摘要" }));
    expect(onClick).toHaveBeenCalledOnce();
    expect(screen.queryByRole("group", { name: "资料操作" })).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });

  it("lets a selected action transfer focus into its newly opened dialog", async () => {
    const user = userEvent.setup();
    function EditAction() {
      const [editing, setEditing] = useState(false);
      return (
        <>
          <ActionMenu>
            <Button onClick={() => setEditing(true)}>编辑资料</Button>
          </ActionMenu>
          <TaskModal open={editing} title="编辑资料" onClose={() => setEditing(false)}>
            <input aria-label="资料标题" />
          </TaskModal>
        </>
      );
    }
    render(<EditAction />);
    await user.click(screen.getByRole("button", { name: "更多操作" }));
    await user.click(screen.getByRole("button", { name: "编辑资料" }));
    expect(screen.getByRole("button", { name: "关闭弹窗" })).toHaveFocus();
    expect(screen.queryByRole("group", { name: "更多操作" })).not.toBeInTheDocument();
  });

  it("keeps normal Link navigation and closes after selecting it", async () => {
    const user = userEvent.setup();
    function Location() {
      return <output>{useLocation().pathname}</output>;
    }
    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <ActionMenu>
          <Link to="/records">查看记录</Link>
        </ActionMenu>
        <Location />
      </MemoryRouter>,
    );
    const trigger = screen.getByRole("button", { name: "更多操作" });
    await user.click(trigger);
    await user.click(screen.getByRole("link", { name: "查看记录" }));
    expect(screen.getByText("/records")).toBeInTheDocument();
    expect(trigger).toHaveFocus();
    expect(trigger).toHaveAttribute("aria-expanded", "false");
  });

  it("closes on an outside click without stealing focus from the clicked control", async () => {
    const user = userEvent.setup();
    render(
      <>
        <ActionMenu>
          <Button>导出摘要</Button>
        </ActionMenu>
        <button>其他操作</button>
      </>,
    );
    await user.click(screen.getByRole("button", { name: "更多操作" }));
    await user.click(screen.getByRole("button", { name: "其他操作" }));
    expect(screen.queryByRole("button", { name: "导出摘要" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "其他操作" })).toHaveFocus();
  });

  it("does not reopen a dismissed disclosure when a busy trigger becomes enabled", async () => {
    const user = userEvent.setup();
    const { rerender } = render(
      <ActionMenu>
        <Button>导出摘要</Button>
      </ActionMenu>,
    );
    await user.click(screen.getByRole("button", { name: "更多操作" }));
    rerender(
      <ActionMenu disabled>
        <Button>导出摘要</Button>
      </ActionMenu>,
    );
    expect(screen.queryByRole("button", { name: "导出摘要" })).not.toBeInTheDocument();
    rerender(
      <ActionMenu>
        <Button>导出摘要</Button>
      </ActionMenu>,
    );
    expect(screen.getByRole("button", { name: "更多操作" })).toHaveAttribute(
      "aria-expanded",
      "false",
    );
  });

  it("keeps portaled actions inside a dialog focus boundary and ignores disabled items", async () => {
    const user = userEvent.setup();
    render(
      <section role="dialog" aria-label="编辑">
        <ActionMenu>
          <Button disabled>禁用项</Button>
          <Button>可用项</Button>
        </ActionMenu>
      </section>,
    );
    await user.click(screen.getByRole("button", { name: "更多操作" }));
    expect(screen.getByRole("dialog")).toContainElement(
      screen.getByRole("button", { name: "可用项" }),
    );
    fireEvent.click(screen.getByRole("button", { name: "禁用项" }));
    expect(screen.getByRole("button", { name: "更多操作" })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
  });
});
