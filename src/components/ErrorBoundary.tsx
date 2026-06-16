import { Component, type ErrorInfo, type ReactNode } from "react";

interface ErrorBoundaryProps {
  children: ReactNode;
  // 可选自定义兜底 UI；不传则用内置友好错误卡片。
  fallback?: ReactNode;
}

interface ErrorBoundaryState {
  hasError: boolean;
}

// 渲染期错误兜底：捕获子树在 render / 生命周期 / 构造阶段抛出的**同步**错误，用友好卡片
// 替代整页白屏，并提供「重试」「返回首页」。
//
// 注意（React Error Boundary 的固有边界）：它**不**捕获事件处理器、异步回调
// （setTimeout / Promise.then / fetch 之后）、以及 boundary 自身的错误——这些需在各自
// 调用点 try/catch，或交由页面级 LoadingError 的 error 态处理（各页已有数据请求的
// try/catch + error 文案）。本组件只兜「渲染崩溃 → 白屏」这一类。
//
// 安全：错误详情（message / 组件栈 / state / API 错误正文）**不**进入用户可见 UI，
// 仅在开发态打印到控制台，避免向终端用户泄露内部实现细节。
export default class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { hasError: false };

  static getDerivedStateFromError(): ErrorBoundaryState {
    return { hasError: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    if (import.meta.env.DEV) {
      // 仅开发期留痕，便于定位；不渲染到 UI。
      console.error("ErrorBoundary caught a render error:", error, info.componentStack);
    }
  }

  private handleRetry = (): void => {
    this.setState({ hasError: false });
  };

  private handleHome = (): void => {
    // 整页导航回首页（用原生跳转，避免依赖可能已处于错误状态的路由上下文）。
    window.location.assign("/");
  };

  render(): ReactNode {
    if (!this.state.hasError) return this.props.children;
    if (this.props.fallback !== undefined) return this.props.fallback;
    return (
      <div className="state-box" role="alert">
        <div className="state-title">页面出现了问题</div>
        <p className="state-desc">
          抱歉，此处内容在加载时发生异常。你可以重试，或返回首页后再试一次。
        </p>
        <div style={{ display: "flex", gap: "0.5rem", justifyContent: "center" }}>
          <button className="btn-small" onClick={this.handleRetry}>
            重试
          </button>
          <button className="btn-small" onClick={this.handleHome}>
            返回首页
          </button>
        </div>
      </div>
    );
  }
}
