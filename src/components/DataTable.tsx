import type { ReactNode } from "react";

// 通用表格壳：列定义 + 行数据 + 空态 / 加载态。默认套用现有 `.ingest-table-wrap`
// / `.ingest-table` 样式，故渲染结果与各页面手写表格一致；需要别的表皮时可用
// wrapClassName / tableClassName 覆盖（如 ws-table）。空态 / 加载态以跨列单行呈现。
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
}

export default function DataTable<T>({
  columns,
  rows,
  rowKey,
  rowClassName,
  emptyText,
  loading = false,
  loadingText = "加载中…",
  wrapClassName = "ingest-table-wrap",
  tableClassName = "ingest-table",
}: DataTableProps<T>) {
  return (
    <div className={wrapClassName}>
      <table className={tableClassName}>
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
              <td colSpan={columns.length}>{loadingText}</td>
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
              <td colSpan={columns.length}>{emptyText}</td>
            </tr>
          ) : null}
        </tbody>
      </table>
    </div>
  );
}
