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
    expect(container.querySelectorAll(".help-section")).toHaveLength(15);
    expect(container.querySelector("#quick-start")).toBeInTheDocument();
    expect(container.querySelector("#roadmap")).toBeInTheDocument();
    expect(container.querySelectorAll(".help-section-icon svg")).toHaveLength(15);
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

  it("覆盖资料编辑、维护闭环、目录发布、MCP 操作与部署公告边界", () => {
    const { container } = render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <HelpPage />
      </MemoryRouter>,
    );

    expect(container.querySelector("#knowledge")).toHaveTextContent("编辑不会改写原始文件");
    expect(container.querySelector("#directories")).toHaveTextContent("先保存草稿，再发布正式目录");
    expect(container.querySelector("#directories")).toHaveTextContent(
      "候选只是管理建议，不会自动归档",
    );
    expect(container.querySelector("#maintenance")).toHaveTextContent("维护人 → 到期复核");
    expect(container.querySelector("#maintenance")).toHaveTextContent("不算纠错证据");
    expect(container.querySelector("#integration")).toHaveTextContent("默认只读");
    expect(container.querySelector("#integration")).toHaveTextContent("不代表都已开放为 MCP 工具");
    expect(container.querySelector("#release-notes")).toHaveTextContent(
      "部署生成草稿不会立即通知用户",
    );
    expect(container.querySelector("#roadmap")).toHaveTextContent("扫描件 OCR 已支持");
    expect(container.querySelector("#ingest")).not.toHaveTextContent("命名不合规不阻断入库");
    expect(container.querySelector("#review")).not.toHaveTextContent("审批通过才完成资产化");

    for (const id of ["directories", "maintenance", "release-notes"]) {
      fireEvent.change(screen.getByLabelText("定位章节"), { target: { value: id } });
      expect(screen.getByRole("link", { name: "跳转到章节" })).toHaveAttribute("href", `#${id}`);
      expect(container.querySelector(`.help-directory a[href="#${id}"]`)).toBeInTheDocument();
    }
  });
});
