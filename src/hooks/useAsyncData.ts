import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "../api/http";

// 统一异步数据获取：收拢各页面重复的 loading / error / data / reload 四件套，
// 并保留原有的两点关键语义：
//   1) 403 → forbidden 单独成态（业务无权时展示无权限骨架，而非普通错误）；
//   2) 竞态保护——只有最后一次 reload 的结果会写入状态，过期请求结果被丢弃。
// fetcher 必须用 useCallback 固定标识，其依赖变化即触发重新加载。
export interface AsyncDataState<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
  forbidden: boolean;
  reload: () => void;
  setData: React.Dispatch<React.SetStateAction<T | null>>;
}

export function useAsyncData<T>(
  fetcher: () => Promise<T>,
  opts: { auto?: boolean; errorMessage?: string } = {},
): AsyncDataState<T> {
  const { auto = true, errorMessage = "加载失败" } = opts;
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(auto);
  const [error, setError] = useState<string | null>(null);
  const [forbidden, setForbidden] = useState(false);
  // 单调递增的请求号；回调写状态前比对，过期请求直接丢弃（竞态保护）。
  const reqId = useRef(0);

  const reload = useCallback(() => {
    const id = ++reqId.current;
    setLoading(true);
    setError(null);
    setForbidden(false);
    fetcher()
      .then((res) => {
        if (id !== reqId.current) return;
        setData(res);
        setLoading(false);
      })
      .catch((e) => {
        if (id !== reqId.current) return;
        if (e instanceof ApiError && e.status === 403) setForbidden(true);
        // 401：会话失效 → 引导重新登录，而非笼统「加载失败」。
        else if (e instanceof ApiError && e.status === 401) setError("登录状态已失效，请重新登录");
        else setError(e instanceof Error ? e.message : errorMessage);
        setLoading(false);
      });
  }, [fetcher, errorMessage]);

  useEffect(() => {
    if (auto) reload();
  }, [auto, reload]);

  return { data, loading, error, forbidden, reload, setData };
}
