import { useCallback, useState } from "react";
import { ApiError } from "../api/http";

// 统一写操作反馈：收拢各页面重复的 actionBusy / actionError / actionNote 三元组。
// run() 包裹一次写动作：开始置 busy 并清空上次反馈，成功可选记 note，
// 失败时优先取 ApiError.message（后端安全文案），否则用兜底文案。
// 返回写动作的结果（失败返回 undefined），调用方据此决定是否刷新列表等后续动作。
export interface ActionFeedback {
  busy: boolean;
  error: string | null;
  note: string | null;
  setError: (v: string | null) => void;
  setNote: (v: string | null) => void;
  run: <T>(
    fn: () => Promise<T>,
    opts?: { successNote?: string; errorMessage?: string }
  ) => Promise<T | undefined>;
}

export function useActionFeedback(): ActionFeedback {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);

  const run = useCallback(
    async <T>(
      fn: () => Promise<T>,
      opts: { successNote?: string; errorMessage?: string } = {}
    ): Promise<T | undefined> => {
      setBusy(true);
      setError(null);
      setNote(null);
      try {
        const result = await fn();
        if (opts.successNote) setNote(opts.successNote);
        return result;
      } catch (e) {
        setError(e instanceof ApiError ? e.message : opts.errorMessage ?? "操作失败");
        return undefined;
      } finally {
        setBusy(false);
      }
    },
    []
  );

  return { busy, error, note, setError, setNote, run };
}
