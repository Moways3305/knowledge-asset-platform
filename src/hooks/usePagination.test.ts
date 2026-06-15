import { describe, it, expect } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { usePagination } from "./usePagination";

const items = Array.from({ length: 25 }, (_, i) => i + 1);

describe("usePagination", () => {
  it("slices the first page and reports page metadata", () => {
    const { result } = renderHook(() => usePagination(items, 10));
    expect(result.current.page).toBe(1);
    expect(result.current.pageCount).toBe(3);
    expect(result.current.total).toBe(25);
    expect(result.current.pageItems).toEqual([1, 2, 3, 4, 5, 6, 7, 8, 9, 10]);
    expect(result.current.hasPrev).toBe(false);
    expect(result.current.hasNext).toBe(true);
  });

  it("advances and goes back through pages", () => {
    const { result } = renderHook(() => usePagination(items, 10));
    act(() => result.current.next());
    expect(result.current.page).toBe(2);
    expect(result.current.pageItems).toEqual([11, 12, 13, 14, 15, 16, 17, 18, 19, 20]);
    act(() => result.current.prev());
    expect(result.current.page).toBe(1);
  });

  it("clamps next at the last page and prev at the first", () => {
    const { result } = renderHook(() => usePagination(items, 10));
    act(() => result.current.setPage(99));
    expect(result.current.page).toBe(3);
    expect(result.current.pageItems).toEqual([21, 22, 23, 24, 25]);
    expect(result.current.hasNext).toBe(false);
    act(() => result.current.prev());
    act(() => result.current.prev());
    act(() => result.current.prev());
    expect(result.current.page).toBe(1);
  });

  it("reset returns to page 1", () => {
    const { result } = renderHook(() => usePagination(items, 5));
    act(() => result.current.setPage(3));
    act(() => result.current.reset());
    expect(result.current.page).toBe(1);
  });
});
