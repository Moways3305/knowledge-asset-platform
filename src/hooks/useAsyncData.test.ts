import { describe, it, expect } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { useAsyncData } from "./useAsyncData";
import { ApiError } from "../api/http";

// fetcher 必须是稳定引用（页面侧用 useCallback 固定）；测试里用常量函数模拟。
describe("useAsyncData error classification", () => {
  it("maps 403 to the forbidden state, not a load error", async () => {
    const fetcher = () => Promise.reject(new ApiError(403, "denied", "people_admin_forbidden"));
    const { result } = renderHook(() => useAsyncData(fetcher));
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.forbidden).toBe(true);
    expect(result.current.error).toBeNull();
  });

  it("maps 401 to a friendly re-login message, not a raw failure", async () => {
    const fetcher = () => Promise.reject(new ApiError(401, "unauthorized"));
    const { result } = renderHook(() => useAsyncData(fetcher));
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.forbidden).toBe(false);
    expect(result.current.error).toBe("登录状态已失效，请重新登录");
  });

  it("uses the backend-provided safe message for other failures", async () => {
    const fetcher = () => Promise.reject(new ApiError(500, "请求未成功，请稍后重试"));
    const { result } = renderHook(() => useAsyncData(fetcher, { errorMessage: "加载失败" }));
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.error).toBe("请求未成功，请稍后重试");
  });
});
