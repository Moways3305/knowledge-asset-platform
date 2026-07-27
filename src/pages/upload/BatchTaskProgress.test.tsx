import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import BatchTaskProgress from "./BatchTaskProgress";

describe("BatchTaskProgress", () => {
  it.each([
    ["waiting", "等待", 0],
    ["processing", "处理中", 50],
    ["success", "成功", 100],
    ["failed", "失败", 100],
  ] as const)("renders an independent progress bar for %s", (state, label, value) => {
    render(<BatchTaskProgress state={state} />);
    const progress = screen.getByRole("progressbar", { name: `批量确认进度：${label}` });
    expect(progress).toHaveAttribute("value", String(value));
    expect(screen.getByRole("status")).toHaveTextContent(label);
  });
});
