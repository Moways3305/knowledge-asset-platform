import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import WorkspaceOutline from "./WorkspaceOutline";

describe("WorkspaceOutline", () => {
  it("navigates only available sections without resetting an unfinished form", () => {
    const scroll = vi.fn();
    render(
      <WorkspaceOutline
        items={[
          { id: "general", label: "基础设置" },
          { id: "members", label: "成员" },
          { id: "restricted", label: "受限设置" },
        ]}
      >
        <section id="general" tabIndex={-1} aria-label="基础设置内容">
          <label>
            项目名称
            <input />
          </label>
        </section>
        <section id="members" tabIndex={-1} aria-label="成员内容">
          成员列表
        </section>
      </WorkspaceOutline>,
    );
    const members = screen.getByRole("region", { name: "成员内容" });
    members.scrollIntoView = scroll;
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "尚未保存的名称" } });
    expect(screen.queryByRole("link", { name: "受限设置" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("link", { name: "成员" }));
    expect(members).toHaveFocus();
    expect(scroll).toHaveBeenCalledOnce();
    expect(screen.getByRole("textbox")).toHaveValue("尚未保存的名称");
    expect(screen.getByRole("link", { name: "成员" })).toHaveAttribute("aria-current", "location");
  });

  it("omits redundant navigation for a single available section", () => {
    render(
      <WorkspaceOutline items={[{ id: "only", label: "设置" }]}>
        <section id="only">配置表单</section>
      </WorkspaceOutline>,
    );
    expect(screen.queryByRole("navigation")).not.toBeInTheDocument();
    expect(screen.getByText("配置表单")).toBeVisible();
  });
});
