import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import StatusBadge from "./StatusBadge";

describe("StatusBadge", () => {
  it("renders the label inside the status-pill base class", () => {
    render(<StatusBadge label="已通过" />);
    const el = screen.getByText("已通过");
    expect(el).toBeInTheDocument();
    expect(el).toHaveClass("status-pill");
  });

  it("appends the variant modifier class", () => {
    render(<StatusBadge label="失败" variant="ig-status-failed" />);
    const el = screen.getByText("失败");
    expect(el).toHaveClass("status-pill");
    expect(el).toHaveClass("ig-status-failed");
  });

  it("sets the title attribute when provided", () => {
    render(<StatusBadge label="索引中" title="知识底座索引状态" />);
    expect(screen.getByText("索引中")).toHaveAttribute("title", "知识底座索引状态");
  });
});
