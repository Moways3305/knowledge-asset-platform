import type { ReactNode } from "react";

// 统一页面三态骨架：按优先级渲染 加载中 / 无权限(forbidden) / 加载失败 / 空态 中的
// 第一个命中项；都不命中则返回 null（由调用方渲染正常内容）。各页面已有的状态容器
// 类名（如 rv-empty-state / kl-empty-state / ig-empty-state）通过 *ClassName 传入，
// 故可在不改变现有视觉的前提下替换页面里成片的三态分支。
interface LoadingErrorProps {
  loading?: boolean;
  forbidden?: boolean;
  error?: string | null;
  empty?: boolean;

  loadingTitle?: ReactNode;
  forbiddenTitle?: ReactNode;
  forbiddenDesc?: ReactNode;
  errorTitle?: ReactNode;
  emptyTitle?: ReactNode;
  emptyDesc?: ReactNode;

  onRetry?: () => void;
  retryText?: string;
  // 空态下附加内容（如「清除筛选」「新建」等动作按钮）。
  children?: ReactNode;

  wrapperClassName?: string;
  titleClassName?: string;
  descClassName?: string;
}

export default function LoadingError({
  loading = false,
  forbidden = false,
  error = null,
  empty = false,
  loadingTitle = "加载中…",
  forbiddenTitle = "无访问权限",
  forbiddenDesc,
  errorTitle = "加载失败",
  emptyTitle = "暂无数据",
  emptyDesc,
  onRetry,
  retryText = "重试",
  children,
  wrapperClassName = "state-box",
  titleClassName = "state-title",
  descClassName = "state-desc",
}: LoadingErrorProps) {
  if (loading) {
    return (
      <div className={wrapperClassName}>
        <div className={titleClassName}>{loadingTitle}</div>
      </div>
    );
  }
  if (forbidden) {
    return (
      <div className={wrapperClassName}>
        <div className={titleClassName}>{forbiddenTitle}</div>
        {forbiddenDesc && <p className={descClassName}>{forbiddenDesc}</p>}
      </div>
    );
  }
  if (error) {
    return (
      <div className={wrapperClassName}>
        <div className={titleClassName}>{errorTitle}</div>
        <p className={descClassName}>{error}</p>
        {onRetry && (
          <button className="btn-small" onClick={onRetry}>
            {retryText}
          </button>
        )}
      </div>
    );
  }
  if (empty) {
    return (
      <div className={wrapperClassName}>
        <div className={titleClassName}>{emptyTitle}</div>
        {emptyDesc && <p className={descClassName}>{emptyDesc}</p>}
        {children}
      </div>
    );
  }
  return null;
}
