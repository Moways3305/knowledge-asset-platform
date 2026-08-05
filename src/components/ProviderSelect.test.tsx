import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import ProviderSelect, { type ProviderSelectOption } from "./ProviderSelect";

const options: ProviderSelectOption[] = [
  { value: "aliyun", label: "阿里云 DashScope" },
  { value: "zhipu", label: "智谱 BigModel" },
  { value: "generic", label: "自定义 (OpenAI兼容接口)" },
];

describe("ProviderSelect", () => {
  it("renders the placeholder when no value is selected", () => {
    render(
      <ProviderSelect options={options} value="" onChange={() => {}} ariaLabel="模型供应商" />,
    );
    expect(screen.getByRole("button", { name: "模型供应商" })).toHaveTextContent("请选择供应商");
  });

  it("opens on click and selects an option", () => {
    const onChange = vi.fn();
    render(
      <ProviderSelect options={options} value="" onChange={onChange} ariaLabel="模型供应商" />,
    );
    fireEvent.click(screen.getByRole("button", { name: "模型供应商" }));
    fireEvent.click(screen.getByRole("option", { name: /智谱 BigModel/ }));
    expect(onChange).toHaveBeenCalledWith("zhipu");
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  });

  it("supports keyboard navigation and Enter to confirm", () => {
    const onChange = vi.fn();
    render(
      <ProviderSelect options={options} value="" onChange={onChange} ariaLabel="模型供应商" />,
    );
    const trigger = screen.getByRole("button", { name: "模型供应商" });
    fireEvent.keyDown(trigger, { key: "ArrowDown" });
    const listbox = screen.getByRole("listbox");
    fireEvent.keyDown(listbox, { key: "ArrowDown" });
    fireEvent.keyDown(listbox, { key: "Enter" });
    expect(onChange).toHaveBeenCalledWith("zhipu");
  });

  it("closes on Escape and restores focus to the trigger", () => {
    render(
      <ProviderSelect
        options={options}
        value="aliyun"
        onChange={() => {}}
        ariaLabel="模型供应商"
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "模型供应商" }));
    expect(screen.getByRole("listbox")).toBeInTheDocument();
    fireEvent.keyDown(screen.getByRole("listbox"), { key: "Escape" });
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "模型供应商" })).toHaveFocus();
  });

  it("closes when clicking outside", () => {
    render(
      <div>
        <button type="button">outside</button>
        <ProviderSelect options={options} value="" onChange={() => {}} ariaLabel="模型供应商" />
      </div>,
    );
    fireEvent.click(screen.getByRole("button", { name: "模型供应商" }));
    expect(screen.getByRole("listbox")).toBeInTheDocument();
    fireEvent.mouseDown(screen.getByRole("button", { name: "outside" }));
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  });
});
