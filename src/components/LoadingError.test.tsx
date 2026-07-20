import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import LoadingError from "./LoadingError";

describe("LoadingError", () => {
  it("没有状态标志时不渲染", () => {
    const { container } = render(<LoadingError />);
    expect(container.firstChild).toBeNull();
  });

  it("加载态优先于无权限、失败和空态", () => {
    render(
      <LoadingError loading forbidden error="raw upstream error" empty loadingTitle="正在读取" />,
    );
    expect(screen.getByRole("status")).toHaveTextContent("正在读取");
    expect(screen.queryByText("无访问权限")).not.toBeInTheDocument();
    expect(screen.queryByText("加载失败")).not.toBeInTheDocument();
  });

  it("无权限态优先于失败和空态，并支持局部动作", () => {
    render(
      <LoadingError
        forbidden
        error="raw upstream error"
        empty
        forbiddenDesc="当前身份只能查看基础信息。"
        forbiddenAction={<button>返回列表</button>}
      />,
    );
    expect(screen.getByRole("alert")).toHaveTextContent("无访问权限");
    expect(screen.getByRole("button", { name: "返回列表" })).toBeInTheDocument();
    expect(screen.queryByText("raw upstream error")).not.toBeInTheDocument();
  });

  it("失败态不展示原始错误，并可重试", () => {
    const onRetry = vi.fn();
    render(<LoadingError error="token=secret upstream body" onRetry={onRetry} />);
    expect(screen.getByRole("alert")).toHaveTextContent("内容暂时无法加载，请稍后重试。");
    expect(screen.queryByText(/token=secret/i)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "重试" }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it("失败态优先于空态", () => {
    render(<LoadingError error="x" empty />);
    expect(screen.getByText("加载失败")).toBeInTheDocument();
    expect(screen.queryByText("暂无数据")).not.toBeInTheDocument();
  });

  it("空态保留自定义容器并带有语义图形", () => {
    const { container } = render(
      <LoadingError empty emptyTitle="暂无数据" wrapperClassName="rv-empty-state">
        <button>创建内容</button>
      </LoadingError>,
    );
    expect(container.querySelector(".rv-empty-state .product-state-icon svg")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "创建内容" })).toBeInTheDocument();
  });
});
