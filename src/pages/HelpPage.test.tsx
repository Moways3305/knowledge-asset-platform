import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { deriveCapabilities } from "../auth/permissions";
import { HELP_GUIDES, searchHelp } from "../content/helpGuides";
import HelpPage from "./HelpPage";

const capabilities = deriveCapabilities(null);
vi.mock("../auth/AuthContext", () => ({ useAuth: () => ({ capabilities }) }));
const open = (url = "/help") =>
  render(
    <MemoryRouter initialEntries={[url]}>
      <HelpPage />
    </MemoryRouter>,
  );
describe("HelpPage discovery and task articles", () => {
  beforeEach(() =>
    Object.assign(capabilities, deriveCapabilities(null), {
      isBusinessUser: true,
      hasProject: true,
    }),
  );
  it("starts with discovery instead of an open article or long directory", () => {
    open();
    expect(screen.getByRole("heading", { name: "帮助中心" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "新手入门" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "功能教程" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "常见问题" })).toBeInTheDocument();
    expect(screen.queryByRole("article")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("帮助目录")).not.toBeInTheDocument();
    fireEvent.click(
      within(screen.getByRole("navigation", { name: "按身份入门" })).getByRole("link", {
        name: "项目经理入门",
      }),
    );
    expect(screen.getByRole("heading", { name: "项目经理入门", level: 2 })).toBeInTheDocument();
    expect(
      within(screen.getByRole("navigation", { name: "相关教程" })).getByRole("link", {
        name: "审批项目入库",
      }),
    ).toBeInTheDocument();
  });
  it("finds a question in article text and opens its tutorial", () => {
    open();
    fireEvent.change(screen.getByLabelText("搜索帮助"), { target: { value: "计算基数" } });
    const results = screen.getByRole("region", { name: "帮助搜索结果" });
    fireEvent.click(within(results).getByRole("link", { name: /项目问答与引用/ }));
    expect(screen.getByRole("heading", { name: "项目问答与引用", level: 2 })).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "帮助搜索结果" })).not.toBeInTheDocument();
  });
  it("filters by category and can return to the landing page", () => {
    open("/help?category=" + encodeURIComponent("审批与资产发布"));
    const list = screen.getByRole("region", { name: "分类教程" });
    expect(within(list).getByRole("link", { name: /审批项目入库/ })).toBeInTheDocument();
    expect(within(list).queryByRole("link", { name: /上传资料到个人库/ })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("link", { name: "帮助首页" }));
    expect(screen.getByRole("heading", { name: "新手入门" })).toBeInTheDocument();
  });
  it("offers recovery from an empty search", () => {
    open("/help?q=zzzz-no-result");
    expect(screen.getByRole("heading", { name: "没有找到相关教程" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("link", { name: "返回帮助首页" }));
    expect(screen.getByLabelText("搜索帮助")).toHaveValue("");
  });
  it("withholds unauthorized operation links but allows reading help", () => {
    open("/help?article=people");
    expect(
      screen.getByRole("heading", { name: "管理人员身份和项目任职", level: 2 }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "打开功能" })).not.toBeInTheDocument();
  });
  it("preserves old deep links and treats unknown articles as the home page", () => {
    const view = open("/help#integration");
    expect(screen.getByRole("heading", { name: "连接外部助手", level: 2 })).toBeInTheDocument();
    expect(screen.getByRole("article")).toHaveTextContent("每次业务操作仍需本人明确授权");
    view.unmount();
    open("/help?article=missing");
    expect(screen.getByRole("heading", { name: "新手入门" })).toBeInTheDocument();
  });
  it("puts the screenshot with its step and closes the mobile directory after selection", () => {
    open("/help?article=ingest");
    const image = screen.getByRole("img", { name: /选择文件、选择文件夹入口/ });
    expect(image.closest("section")).toHaveTextContent("选择本地文件");
    expect(image.closest("section")).not.toHaveTextContent("将“目标知识库”选为个人库");
    fireEvent.click(screen.getByRole("button", { name: "本类教程" }));
    expect(screen.getByRole("button", { name: "本类教程" })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
    fireEvent.click(
      within(screen.getByRole("navigation", { name: "本类教程" })).getByRole("link", {
        name: "上传资料到项目库",
      }),
    );
    expect(screen.getByRole("heading", { name: "上传资料到项目库", level: 2 })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "本类教程" })).toHaveAttribute(
      "aria-expanded",
      "false",
    );
    expect(screen.getByRole("article")).toHaveTextContent("等待项目经理确认");
  });
  it("has valid related tutorials and unique section anchors", () => {
    const ids = new Set(HELP_GUIDES.map((guide) => guide.id));
    expect(ids.size).toBe(HELP_GUIDES.length);
    for (const guide of HELP_GUIDES) {
      expect(guide.sections.length).toBeGreaterThan(0);
      expect(new Set(guide.sections.map((section) => section.id)).size).toBe(guide.sections.length);
      for (const id of guide.related) expect(ids.has(id), id).toBe(true);
    }
    expect(searchHelp("mcp OAuth").map((guide) => guide.id)).toContain("integration");
  });
});
