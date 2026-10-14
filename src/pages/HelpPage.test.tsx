import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import HelpPage from "./HelpPage";

describe("HelpPage", () => {
  it("按工作流呈现当前操作章节，不保留旧规划章节", () => {
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
    expect(container.querySelectorAll(".help-section")).toHaveLength(14);
    expect(container.querySelector("#quick-start")).toBeInTheDocument();
    expect(container.querySelector("#roadmap")).not.toBeInTheDocument();
    expect(container.querySelectorAll(".help-section-icon svg")).toHaveLength(14);
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
    expect(container.querySelector("#knowledge")).toHaveTextContent("未命中不等于资料不存在");
    expect(container.querySelector("#models")).toHaveTextContent("平台保存的默认模型");
    expect(container.querySelector("#integration")).toHaveTextContent("资料卡片不等于问题已有答案");
    expect(container.querySelector("#directories")).toHaveTextContent("保存草稿后还需发布");
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
    expect(container.querySelector("#ingest")).toHaveTextContent("扫描件可进入 OCR 处理");
    expect(container.querySelector("#ingest")).not.toHaveTextContent("命名不合规不阻断入库");
    expect(container.querySelector("#review")).not.toHaveTextContent("审批通过才完成资产化");

    for (const id of ["directories", "maintenance", "release-notes"]) {
      fireEvent.change(screen.getByLabelText("定位章节"), { target: { value: id } });
      expect(screen.getByRole("link", { name: "跳转到章节" })).toHaveAttribute("href", `#${id}`);
      expect(container.querySelector(`.help-directory a[href="#${id}"]`)).toBeInTheDocument();
    }
  });

  it("删除过时入口、未发布功能、重复技术说明，使用当前菜单与弹窗入口", () => {
    const { container } = render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <HelpPage />
      </MemoryRouter>,
    );
    expect(container.querySelector("#identity")).toHaveTextContent("登录与工作身份");
    expect(container.querySelector("#maintenance")).toHaveTextContent(
      "在资料详情点击「知识维护与复核」",
    );
    expect(container.querySelector("#maintenance")).toHaveTextContent("弹窗");
    expect(container.querySelector("#directories")).toHaveTextContent("「目录治理」");
    expect(container.querySelector("#directories")).toHaveTextContent("「新建目录」");
    expect(container.querySelector("#directories")).toHaveTextContent("该项目的有效项目经理");
    expect(container.querySelector("#directories")).toHaveTextContent("不发布其他草稿");
    expect(container.querySelector("#release-notes")).toHaveTextContent("侧栏底部「更新日志」");
    expect(container.querySelector("#original-access")).toHaveTextContent("原文预览为只读");
    for (const obsolete of [
      "Kivo",
      "后续增强",
      "仍为规划",
      "待增强",
      "新建三级目录",
      "permission_rules",
      "WECOM_",
      "in_app",
      "material → asset",
      "脱敏 label",
      "cookie",
      "CSRF",
      "reparse",
    ]) {
      expect(container).not.toHaveTextContent(obsolete);
    }
    expect(screen.queryByRole("option", { name: /功能边界|后续增强/ })).not.toBeInTheDocument();
  });
});
