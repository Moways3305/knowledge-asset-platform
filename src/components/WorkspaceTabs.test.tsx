import { useState } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import WorkspaceTabs from "./WorkspaceTabs";

function Example() {
  const [view, setView] = useState("read");
  return (
    <WorkspaceTabs
      label="资料导航"
      value={view}
      onChange={setView}
      items={[
        { key: "read", label: "内容摘要", content: <p>可见摘要</p> },
        {
          key: "manage",
          label: "维护与发布",
          content: (
            <label>
              维护原因
              <input />
            </label>
          ),
        },
      ]}
    />
  );
}

describe("WorkspaceTabs", () => {
  it("supports keyboard navigation and exposes only the selected panel", () => {
    render(<Example />);
    const first = screen.getByRole("tab", { name: "内容摘要" });
    first.focus();
    fireEvent.keyDown(first, { key: "ArrowRight" });
    expect(screen.getByRole("tab", { name: "维护与发布" })).toHaveFocus();
    expect(screen.getByRole("tabpanel")).toHaveAccessibleName("维护与发布");
    expect(screen.getByText("可见摘要")).not.toBeVisible();
    fireEvent.keyDown(document.activeElement!, { key: "Home" });
    expect(first).toHaveFocus();
    expect(first).toHaveAttribute("aria-selected", "true");
  });
  it("preserves an in-progress input when the user switches views", () => {
    render(<Example />);
    fireEvent.click(screen.getByRole("tab", { name: "维护与发布" }));
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "待核查内容" } });
    fireEvent.click(screen.getByRole("tab", { name: "内容摘要" }));
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "维护与发布" }));
    expect(screen.getByRole("textbox")).toHaveValue("待核查内容");
  });
});
