import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen } from "@testing-library/react";
import ErrorBoundary from "./ErrorBoundary";

// 故意抛错的子组件，用于触发 boundary。
function Boom(): never {
  throw new Error("boom");
}

describe("ErrorBoundary", () => {
  beforeEach(() => {
    // React 在捕获渲染错误时会向 console.error 打印；这里静音以保持测试输出干净。
    vi.spyOn(console, "error").mockImplementation(() => {});
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("正常渲染时透传子节点", () => {
    render(
      <ErrorBoundary>
        <p>内容正常</p>
      </ErrorBoundary>,
    );
    expect(screen.getByText("内容正常")).toBeInTheDocument();
  });

  it("子树渲染崩溃时显示友好兜底，且不泄露错误详情", () => {
    render(
      <ErrorBoundary>
        <Boom />
      </ErrorBoundary>,
    );
    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(screen.getByText("页面出现了问题")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "重试" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "返回首页" })).toBeInTheDocument();
    // 不得把内部错误 message 暴露到用户 UI。
    expect(screen.queryByText(/boom/i)).not.toBeInTheDocument();
  });

  it("支持自定义 fallback", () => {
    render(
      <ErrorBoundary fallback={<div>自定义兜底</div>}>
        <Boom />
      </ErrorBoundary>,
    );
    expect(screen.getByText("自定义兜底")).toBeInTheDocument();
  });
});
