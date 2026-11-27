import { act, fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { WorkspaceAgent } from "../../api/aiWorkspace";
import AgentPicker from "./AgentPicker";

const agents: WorkspaceAgent[] = [
  {
    key: "maintenance",
    label: "知识维护 Agent",
    description: "检查知识并跟进需要处理的问题",
    tools: [],
  },
  { key: "research", label: "研究 Agent", description: "整理资料与研究结论", tools: [] },
];

function Fixture({
  initial = null,
  options = agents,
  disabled = false,
  onChange = vi.fn(),
}: {
  initial?: string | null;
  options?: WorkspaceAgent[];
  disabled?: boolean;
  onChange?: (value: string | null) => void;
}) {
  const [value, setValue] = useState(initial);
  return (
    <div className="ai-workspace" data-testid="workspace">
      <form className="aw-composer" onSubmit={(event) => event.preventDefault()}>
        <button type="button">上一项</button>
        <AgentPicker
          agents={options}
          value={value}
          disabled={disabled}
          onChange={(next) => {
            onChange(next);
            setValue(next);
          }}
        />
        <button type="button">下一项</button>
      </form>
      <p>空白区域</p>
    </div>
  );
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("composer Agent picker", () => {
  it("keeps the default trigger icon-only, selects an Agent in a portal and removes it", async () => {
    const user = userEvent.setup();
    const changed = vi.fn();
    render(<Fixture onChange={changed} />);
    const trigger = screen.getByRole("button", { name: "添加智能体" });
    expect(trigger).toHaveTextContent("");
    fireEvent.pointerOver(trigger, { pointerType: "mouse" });
    expect(screen.getByRole("tooltip")).toHaveTextContent("添加智能体");
    await user.click(trigger);
    const menu = screen.getByRole("menu", { name: "选择智能体" });
    expect(menu.parentElement).toBe(screen.getByTestId("workspace"));
    expect(menu.closest(".aw-composer")).toBeNull();
    const option = within(menu).getByRole("menuitemradio", { name: "知识维护 Agent" });
    expect(option).toHaveAccessibleDescription(agents[0].description);
    await user.click(option);
    expect(changed).toHaveBeenLastCalledWith("maintenance");
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
    expect(trigger).toHaveTextContent("知识维护 Agent");
    await user.click(trigger);
    expect(screen.getByRole("menuitemradio", { name: "知识维护 Agent" })).toHaveAttribute(
      "aria-checked",
      "true",
    );
    await user.click(screen.getByRole("menuitemradio", { name: "通用对话" }));
    expect(changed).toHaveBeenLastCalledWith(null);
    expect(trigger).toHaveTextContent("");
  });

  it("moves real keyboard focus, wraps arrows, supports Home/End and selection", async () => {
    const user = userEvent.setup();
    const changed = vi.fn();
    render(<Fixture onChange={changed} />);
    const trigger = screen.getByRole("button", { name: "添加智能体" });
    act(() => trigger.focus());
    await user.keyboard("{ArrowDown}");
    expect(screen.getByRole("menuitemradio", { name: "通用对话" })).toHaveFocus();
    await user.keyboard("{End}");
    expect(screen.getByRole("menuitemradio", { name: "研究 Agent" })).toHaveFocus();
    await user.keyboard("{ArrowDown}");
    expect(screen.getByRole("menuitemradio", { name: "通用对话" })).toHaveFocus();
    await user.keyboard("{ArrowUp}");
    expect(screen.getByRole("menuitemradio", { name: "研究 Agent" })).toHaveFocus();
    await user.keyboard("{Home}{ArrowDown}{Enter}");
    expect(changed).toHaveBeenCalledWith("maintenance");
    expect(trigger).toHaveFocus();
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    await user.keyboard(" ");
    expect(screen.getByRole("menuitemradio", { name: "知识维护 Agent" })).toHaveFocus();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
    expect(changed).toHaveBeenCalledTimes(1);
  });

  it("returns Tab to composer order instead of the portal's DOM position", async () => {
    const user = userEvent.setup();
    render(<Fixture />);
    const trigger = screen.getByRole("button", { name: "添加智能体" });
    await user.click(trigger);
    await user.tab();
    expect(screen.getByRole("button", { name: "下一项" })).toHaveFocus();
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    await user.click(trigger);
    await user.tab({ shift: true });
    expect(screen.getByRole("button", { name: "上一项" })).toHaveFocus();
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });

  it("dismisses outside clicks without stealing focus from another clicked control", async () => {
    const user = userEvent.setup();
    render(<Fixture />);
    const trigger = screen.getByRole("button", { name: "添加智能体" });
    await user.click(trigger);
    fireEvent.pointerDown(screen.getByText("空白区域"));
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
    await user.click(trigger);
    await user.click(screen.getByRole("button", { name: "下一项" }));
    expect(screen.getByRole("button", { name: "下一项" })).toHaveFocus();
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });

  it("allows touch selection and closes an open menu when submission disables the picker", async () => {
    const user = userEvent.setup();
    const changed = vi.fn();
    const { rerender } = render(<Fixture onChange={changed} />);
    const trigger = screen.getByRole("button", { name: "添加智能体" });
    fireEvent.pointerDown(trigger, { pointerType: "touch" });
    fireEvent.click(trigger);
    expect(screen.getByRole("menu")).toBeInTheDocument();
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
    await user.click(screen.getByRole("menuitemradio", { name: "知识维护 Agent" }));
    expect(changed).toHaveBeenCalledOnce();
    await user.click(trigger);
    rerender(<Fixture onChange={changed} disabled />);
    expect(trigger).toBeDisabled();
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    fireEvent.click(trigger);
    fireEvent.keyDown(trigger, { key: "ArrowDown" });
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    expect(changed).toHaveBeenCalledOnce();
  });

  it("explains loading and empty options, and lets an unknown selection return to general chat", async () => {
    const user = userEvent.setup();
    const changed = vi.fn();
    const { rerender } = render(
      <div className="ai-workspace">
        <AgentPicker agents={undefined} value={null} onChange={changed} />
      </div>,
    );
    await user.click(screen.getByRole("button", { name: "添加智能体" }));
    expect(screen.getByRole("status")).toHaveTextContent("正在读取智能体列表");
    expect(screen.getByRole("menuitemradio", { name: "通用对话" })).toHaveAttribute(
      "aria-checked",
      "true",
    );
    rerender(
      <div className="ai-workspace">
        <AgentPicker agents={[]} value="removed-agent" onChange={changed} />
      </div>,
    );
    expect(screen.getByText("此前选择的智能体不可用，可切回通用对话。")).toBeInTheDocument();
    expect(screen.getByText("暂无可用智能体，可以继续通用对话。")).toBeInTheDocument();
    await user.click(screen.getByRole("menuitemradio", { name: "通用对话" }));
    expect(changed).toHaveBeenCalledWith(null);
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });

  it("clamps a tall menu inside a narrow, short viewport and flips below near the top", async () => {
    const user = userEvent.setup();
    vi.spyOn(window, "innerWidth", "get").mockReturnValue(280);
    vi.spyOn(window, "innerHeight", "get").mockReturnValue(180);
    vi.spyOn(HTMLElement.prototype, "scrollHeight", "get").mockReturnValue(500);
    render(<Fixture />);
    const trigger = screen.getByRole("button", { name: "添加智能体" });
    const rect = vi.spyOn(trigger, "getBoundingClientRect").mockReturnValue({
      left: 230,
      top: 120,
      bottom: 152,
      right: 262,
      width: 32,
      height: 32,
      x: 230,
      y: 120,
      toJSON: () => ({}),
    });
    await user.click(trigger);
    const menu = screen.getByRole("menu");
    expect(menu).toHaveStyle({ left: "12px", top: "12px", width: "256px", maxHeight: "100px" });
    rect.mockReturnValue({
      left: 0,
      top: 10,
      bottom: 42,
      right: 32,
      width: 32,
      height: 32,
      x: 0,
      y: 10,
      toJSON: () => ({}),
    });
    fireEvent(window, new Event("resize"));
    expect(menu).toHaveStyle({ left: "12px", top: "50px", maxHeight: "118px" });
  });

  it("scrolls the selected and keyboard-active options into the menu without moving the workspace", async () => {
    const user = userEvent.setup();
    const pageScroll = vi.spyOn(window, "scrollTo");
    const rect = (top: number, height: number) => ({
      left: 20,
      right: 340,
      top,
      bottom: top + height,
      width: 320,
      height,
      x: 20,
      y: top,
      toJSON: () => ({}),
    });
    vi.spyOn(HTMLElement.prototype, "clientHeight", "get").mockImplementation(function (
      this: HTMLElement,
    ) {
      return this.getAttribute("role") === "menu" ? 90 : 0;
    });
    vi.spyOn(HTMLElement.prototype, "clientTop", "get").mockReturnValue(1);
    vi.spyOn(HTMLElement.prototype, "scrollHeight", "get").mockReturnValue(190);
    vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(function (
      this: HTMLElement,
    ) {
      if (this.getAttribute("role") === "menu") return rect(50, 92);
      if (this.getAttribute("role") === "menuitemradio") {
        const container = this.parentElement!;
        const index = [...container.querySelectorAll('[role="menuitemradio"]')].indexOf(this);
        return rect(51 + 28 + index * 54 - container.scrollTop, 54);
      }
      return rect(300, 32);
    });
    render(<Fixture initial="research" />);
    const workspace = screen.getByTestId("workspace");
    workspace.scrollTop = 260;
    await user.click(screen.getByRole("button", { name: "添加智能体" }));
    const menu = screen.getByRole("menu");
    const expectVisibleFocus = (name: string) => {
      const option = screen.getByRole("menuitemradio", { name });
      expect(option).toHaveFocus();
      const bounds = option.getBoundingClientRect();
      expect(bounds.top).toBeGreaterThanOrEqual(51);
      expect(bounds.bottom).toBeLessThanOrEqual(141);
      expect(workspace.scrollTop).toBe(260);
      expect(pageScroll).not.toHaveBeenCalled();
    };
    expectVisibleFocus("研究 Agent");
    expect(menu.scrollTop).toBe(100);
    await user.keyboard("{Home}");
    expectVisibleFocus("通用对话");
    expect(menu.scrollTop).toBe(28);
    await user.keyboard("{ArrowDown}");
    expectVisibleFocus("知识维护 Agent");
    expect(menu.scrollTop).toBe(46);
    await user.keyboard("{End}");
    expectVisibleFocus("研究 Agent");
    expect(menu.scrollTop).toBe(100);
  });
});
