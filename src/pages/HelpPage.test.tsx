import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import HelpPage from "./HelpPage";

describe("HelpPage", () => {
  it("按工作流呈现目录和全部既有帮助章节", () => {
    const { container } = render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <HelpPage />
      </MemoryRouter>,
    );

    expect(screen.getByRole("heading", { name: "帮助中心" })).toBeInTheDocument();
    expect(screen.getByLabelText("帮助目录")).toBeInTheDocument();
    expect(screen.getAllByText("开始使用")).toHaveLength(2);
    expect(screen.getAllByText("知识资产与项目")).toHaveLength(2);
    expect(screen.getAllByText("管理员治理与安全")).toHaveLength(2);
    expect(container.querySelectorAll(".help-section")).toHaveLength(12);
    expect(container.querySelector("#quick-start")).toBeInTheDocument();
    expect(container.querySelector("#roadmap")).toBeInTheDocument();
    expect(container.querySelectorAll(".help-section-icon svg")).toHaveLength(12);
  });

  it("章节选择器生成真实页内跳转，并保留真实产品入口", () => {
    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <HelpPage />
      </MemoryRouter>,
    );

    fireEvent.change(screen.getByLabelText("定位章节"), { target: { value: "review" } });
    expect(screen.getByRole("link", { name: "跳转到章节" })).toHaveAttribute("href", "#review");
    expect(document.querySelector('.help-footer a[href="/knowledge"]')).toBeInTheDocument();
  });
});
