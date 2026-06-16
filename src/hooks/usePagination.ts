import { useMemo, useState } from "react";

// 通用客户端分页：给定完整数组与每页条数，返回当前页切片与翻页控制。
// 页码越界（如筛选后总数变少）自动夹紧到有效范围，避免出现空白页。
export interface Pagination<T> {
  page: number;
  pageSize: number;
  pageCount: number;
  pageItems: T[];
  total: number;
  setPage: (p: number) => void;
  next: () => void;
  prev: () => void;
  reset: () => void;
  hasPrev: boolean;
  hasNext: boolean;
}

export function usePagination<T>(items: T[], pageSize = 20): Pagination<T> {
  const [page, setPageRaw] = useState(1);
  const total = items.length;
  const pageCount = Math.max(1, Math.ceil(total / pageSize));
  // 当前页始终夹紧到有效范围（筛选后总数变少时不出现空白页）。
  const current = Math.min(Math.max(1, page), pageCount);

  // 所有翻页入口都从夹紧后的 current 出发，并再次夹紧，避免越界页码卡死。
  const setPage = (p: number) => setPageRaw(Math.min(Math.max(1, p), pageCount));

  const pageItems = useMemo(
    () => items.slice((current - 1) * pageSize, current * pageSize),
    [items, current, pageSize],
  );

  return {
    page: current,
    pageSize,
    pageCount,
    pageItems,
    total,
    setPage,
    next: () => setPage(current + 1),
    prev: () => setPage(current - 1),
    reset: () => setPageRaw(1),
    hasPrev: current > 1,
    hasNext: current < pageCount,
  };
}
