import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import LoadingError from "./LoadingError";

describe("LoadingError", () => {
  it("renders nothing when no state flag is active", () => {
    const { container } = render(<LoadingError />);
    expect(container.firstChild).toBeNull();
  });

  it("shows the loading title first when loading", () => {
    render(<LoadingError loading loadingTitle="加载中…" />);
    expect(screen.getByText("加载中…")).toBeInTheDocument();
  });

  it("shows forbidden state with title and description", () => {
    render(<LoadingError forbidden forbiddenTitle="无访问权限" forbiddenDesc="仅业务用户可见" />);
    expect(screen.getByText("无访问权限")).toBeInTheDocument();
    expect(screen.getByText("仅业务用户可见")).toBeInTheDocument();
  });

  it("shows the error message and calls onRetry when retry clicked", () => {
    const onRetry = vi.fn();
    render(<LoadingError error="后端未启动" onRetry={onRetry} retryText="重试" />);
    expect(screen.getByText("后端未启动")).toBeInTheDocument();
    fireEvent.click(screen.getByText("重试"));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it("prioritizes loading over error/empty", () => {
    render(<LoadingError loading error="x" empty loadingTitle="加载中…" />);
    expect(screen.getByText("加载中…")).toBeInTheDocument();
    expect(screen.queryByText("x")).not.toBeInTheDocument();
  });

  it("renders empty state and applies custom wrapper class", () => {
    const { container } = render(
      <LoadingError empty emptyTitle="暂无数据" wrapperClassName="rv-empty-state" titleClassName="rv-empty-title" />
    );
    expect(screen.getByText("暂无数据")).toBeInTheDocument();
    expect(container.querySelector(".rv-empty-state .rv-empty-title")).toBeInTheDocument();
  });
});
