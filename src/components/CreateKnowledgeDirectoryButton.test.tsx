import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import CreateKnowledgeDirectoryButton from "./CreateKnowledgeDirectoryButton";

const mocks = vi.hoisted(() => ({ list: vi.fn(), create: vi.fn() }));
vi.mock("../api/knowledge", () => ({ fetchKnowledgeDirectories: mocks.list }));
vi.mock("../api/http", () => ({ apiPost: mocks.create }));

function Location() {
  return <output aria-label="当前路径">{useLocation().search}</output>;
}
function mount(scope: "company" | "project" = "company") {
  return render(
    <MemoryRouter>
      <CreateKnowledgeDirectoryButton
        scope={scope}
        projectId={scope === "project" ? "project-a" : undefined}
      />
      <Location />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  mocks.list.mockResolvedValue([
    { directory_key: "company.methodology", scope: "company", name: "方法论", parent_key: null },
    {
      directory_key: "company.custom_old",
      scope: "company",
      name: "已有子目录",
      parent_key: "company.methodology",
    },
  ]);
  mocks.create.mockResolvedValue({ directory_key: "company.custom_new" });
});

describe("新建知识库目录", () => {
  it("只选标准分类，创建后进入目录而不是发布草稿", async () => {
    mount();
    fireEvent.click(screen.getByRole("button", { name: "新建目录" }));
    await screen.findByRole("option", { name: "方法论" });
    expect(screen.queryByRole("option", { name: "已有子目录" })).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("目录名称"), { target: { value: "操作模板" } });
    fireEvent.click(screen.getByRole("button", { name: "创建目录" }));
    await waitFor(() =>
      expect(mocks.create).toHaveBeenCalledWith("/api/v1/knowledge/directories", {
        scope: "company",
        project_id: null,
        parent_key: "company.methodology",
        display_name: "操作模板",
      }),
    );
    await waitFor(() =>
      expect(screen.getByLabelText("当前路径")).toHaveTextContent(
        "directory_key=company.custom_new",
      ),
    );
  });

  it("失败保留输入并展示后端拒绝，不跳走", async () => {
    mocks.create.mockRejectedValue(new Error("当前分类下已存在同名目录"));
    mount();
    fireEvent.click(screen.getByRole("button", { name: "新建目录" }));
    await screen.findByRole("option", { name: "方法论" });
    fireEvent.change(screen.getByLabelText("目录名称"), { target: { value: "操作模板" } });
    fireEvent.click(screen.getByRole("button", { name: "创建目录" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("同名目录");
    expect(screen.getByLabelText("目录名称")).toHaveValue("操作模板");
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("项目创建绑定当前项目", async () => {
    mocks.list.mockResolvedValue([
      { directory_key: "project.deliverables", name: "成果", parent_key: null },
    ]);
    mocks.create.mockResolvedValue({ directory_key: "project.custom_new" });
    mount("project");
    fireEvent.click(screen.getByRole("button", { name: "新建目录" }));
    await screen.findByRole("option", { name: "成果" });
    fireEvent.change(screen.getByLabelText("目录名称"), { target: { value: "报告" } });
    fireEvent.click(screen.getByRole("button", { name: "创建目录" }));
    await waitFor(() =>
      expect(mocks.create).toHaveBeenCalledWith("/api/v1/knowledge/directories", {
        scope: "project",
        project_id: "project-a",
        parent_key: "project.deliverables",
        display_name: "报告",
      }),
    );
    await waitFor(() =>
      expect(screen.getByLabelText("当前路径")).toHaveTextContent("project_id=project-a"),
    );
  });
});
