import type { ReactNode } from "react";
import { Inbox, LoaderCircle, MoveHorizontal } from "lucide-react";

// 通用表格壳：列定义 + 行数据 + 空态 / 加载态。默认使用产品级表格类；尚未逐页迁移
// 的页面可通过 className 显式兼容旧表皮，避免默认实现依赖某个业务页面。
export interface Column<T> {
  key: string;
  header: ReactNode;
  render: (row: T) => ReactNode;
  className?: string; // td 类
  headerClassName?: string; // th 类
}

interface DataTableProps<T> {
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string;
  rowClassName?: (row: T) => string | undefined;
  emptyText?: ReactNode;
  loading?: boolean;
  loadingText?: ReactNode;
  wrapClassName?: string;
  tableClassName?: string;
  ariaLabel?: string;
  scrollHint?: ReactNode;
}

export default function DataTable<T>({
  columns,
  rows,
  rowKey,
  rowClassName,
  emptyText,
  loading = false,
  loadingText = "加载中…",
  wrapClassName = "product-table-wrap",
  tableClassName = "product-data-table",
  ariaLabel,
  scrollHint = "左右滑动查看完整表格",
}: DataTableProps<T>) {
  return (
    <div className="product-table-region">
      <div className="product-table-scroll-hint" role="note">
        <MoveHorizontal size={14} aria-hidden="true" />
        {scrollHint}
      </div>
      <div
        className={wrapClassName}
        data-table-scroll
        tabIndex={0}
        role="region"
        aria-label={ariaLabel ? `${ariaLabel}，可横向滚动` : "可横向滚动的表格"}
      >
        <table className={tableClassName} aria-label={ariaLabel} aria-busy={loading}>
          <thead>
            <tr>
              {columns.map((c) => (
                <th key={c.key} className={c.headerClassName}>
                  {c.header}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr>
                <td className="product-table-state" colSpan={columns.length}>
                  <span className="product-table-state-content" role="status" aria-live="polite">
                    <LoaderCircle className="product-state-spinner" size={18} aria-hidden="true" />
                    {loadingText}
                  </span>
                </td>
              </tr>
            ) : rows.length > 0 ? (
              rows.map((row) => (
                <tr key={rowKey(row)} className={rowClassName?.(row)}>
                  {columns.map((c) => (
                    <td key={c.key} className={c.className}>
                      {c.render(row)}
                    </td>
                  ))}
                </tr>
              ))
            ) : emptyText != null ? (
              <tr>
                <td className="product-table-state" colSpan={columns.length}>
                  {typeof emptyText === "string" || typeof emptyText === "number" ? (
                    <div className="product-table-state-content is-empty">
                      <Inbox size={18} aria-hidden="true" />
                      {emptyText}
                    </div>
                  ) : (
                    emptyText
                  )}
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
    </div>
  );
}
