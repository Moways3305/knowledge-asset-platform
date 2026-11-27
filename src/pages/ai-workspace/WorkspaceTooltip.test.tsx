import { act, fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import {
  WorkspaceIconButton,
  WorkspaceTooltip,
  positionWorkspaceTooltip,
} from "./WorkspaceTooltip";

describe("workspace icon tooltips", () => {
  it("reveals the label on hover and dismisses Escape while focus remains elsewhere", () => {
    const onParentKey = vi.fn();
    render(
      <div onKeyDown={onParentKey}>
        <textarea aria-label="消息" />
        <WorkspaceIconButton label="添加上下文">
          <svg aria-hidden="true" />
        </WorkspaceIconButton>
      </div>,
    );
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
    const trigger = screen.getByRole("button", { name: "添加上下文" });
    expect(trigger).toHaveTextContent("");
    fireEvent.pointerOver(trigger, { pointerType: "mouse" });
    expect(screen.getByRole("tooltip")).toHaveTextContent("添加上下文");
    fireEvent.keyDown(screen.getByLabelText("消息"), { key: "Escape" });
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
    expect(onParentKey).not.toHaveBeenCalled();
  });

  it("describes a keyboard-focused icon and clears the portal on activation", () => {
    const action = vi.fn();
    render(
      <WorkspaceIconButton label="关闭预览" onClick={action}>
        <svg aria-hidden="true" />
      </WorkspaceIconButton>,
    );
    const trigger = screen.getByRole("button", { name: "关闭预览" });
    // jsdom has no keyboard-modality engine for the browser's :focus-visible state.
    const visibleFocus = vi.spyOn(trigger, "matches").mockReturnValue(true);
    act(() => trigger.focus());
    visibleFocus.mockRestore();
    expect(screen.getByRole("tooltip")).toBeInTheDocument();
    expect(trigger).toHaveAccessibleDescription("关闭预览");
    fireEvent.click(trigger);
    expect(action).toHaveBeenCalledOnce();
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
  });

  it("does not show a sticky tooltip after a touch press", () => {
    render(
      <WorkspaceIconButton label="发送消息">
        <svg aria-hidden="true" />
      </WorkspaceIconButton>,
    );
    const trigger = screen.getByRole("button", { name: "发送消息" });
    fireEvent.pointerDown(trigger, { pointerType: "touch" });
    fireEvent.click(trigger);
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
  });

  it("keeps native model options keyboard-operable with the selected model in its description", () => {
    render(
      <WorkspaceTooltip label="对话模型：模型一">
        <select aria-label="对话模型" defaultValue="one">
          <option value="one">模型一</option>
          <option value="two">模型二</option>
        </select>
      </WorkspaceTooltip>,
    );
    const picker = screen.getByRole("combobox", { name: "对话模型" });
    const visibleFocus = vi.spyOn(picker, "matches").mockReturnValue(true);
    act(() => picker.focus());
    visibleFocus.mockRestore();
    expect(picker).toHaveAccessibleDescription("对话模型：模型一");
    fireEvent.change(picker, { target: { value: "two" } });
    expect(picker).toHaveValue("two");
  });

  it("clamps to the viewport and flips below a trigger near the top", () => {
    expect(
      positionWorkspaceTooltip(
        { left: 286, top: 2, width: 32, height: 32, bottom: 34 },
        { width: 240, height: 50 },
        { width: 320, height: 640 },
      ),
    ).toEqual({ left: 72, top: 42 });
    expect(
      positionWorkspaceTooltip(
        { left: 0, top: 608, width: 32, height: 32, bottom: 640 },
        { width: 240, height: 50 },
        { width: 320, height: 640 },
      ),
    ).toEqual({ left: 8, top: 550 });
  });
});
