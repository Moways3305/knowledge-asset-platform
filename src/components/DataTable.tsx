import type { ReactNode } from "react";

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
}: DataTableProps<T>) {
  return (
    <div className={wrapClassName} data-table-scroll>
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
                {loadingText}
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
                {emptyText}
              </td>
            </tr>
          ) : null}
        </tbody>
      </table>
    </div>
  );
}
