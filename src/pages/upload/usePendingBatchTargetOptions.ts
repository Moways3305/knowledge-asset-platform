import { useEffect, useRef, useState } from "react";
import type { NamingOptionsDTO } from "../../types/naming";
import { commandErrorMessage, fetchNamingOptions } from "./pendingBatchCommands";
import type { TargetLibrary } from "./uploadConstants";

export function usePendingBatchTargetOptions({
  open,
  stage,
  targetLibrary,
  targetProjectId,
}: {
  open: boolean;
  stage: "target" | "review";
  targetLibrary: TargetLibrary;
  targetProjectId: string;
}) {
  const [options, setOptions] = useState<NamingOptionsDTO | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [retryKey, setRetryKey] = useState(0);
  const runRef = useRef(0);
  const pendingRef = useRef<Promise<NamingOptionsDTO> | null>(null);

  const reset = () => {
    ++runRef.current;
    pendingRef.current = null;
    setOptions(null);
    setBusy(false);
    setError(null);
  };

  const get = async (scope: Exclude<TargetLibrary, "">, projectId?: string) => {
    if (options) return options;
    const value = await (pendingRef.current ?? fetchNamingOptions(scope, projectId));
    setOptions(value);
    return value;
  };

  useEffect(() => {
    const canLoad =
      targetLibrary === "personal" ||
      targetLibrary === "company" ||
      (targetLibrary === "project" && Boolean(targetProjectId));
    if (!open || stage !== "target" || !canLoad) return;
    const runId = ++runRef.current;
    setBusy(true);
    setError(null);
    setOptions(null);
    const request = fetchNamingOptions(
      targetLibrary as Exclude<TargetLibrary, "">,
      targetProjectId || undefined,
    );
    pendingRef.current = request;
    void request
      .then((value) => {
        if (runRef.current === runId) setOptions(value);
      })
      .catch((caught) => {
        if (runRef.current !== runId) return;
        setError(
          targetLibrary === "personal"
            ? "个人目录暂时无法加载，请重试。"
            : commandErrorMessage(caught, "目录类别暂时无法加载，将在下一步重试。"),
        );
      })
      .finally(() => {
        if (runRef.current === runId) {
          pendingRef.current = null;
          setBusy(false);
        }
      });
  }, [open, retryKey, stage, targetLibrary, targetProjectId]);

  return {
    options,
    setOptions,
    busy,
    error,
    get,
    reset,
    retry: () => setRetryKey((value) => value + 1),
  };
}
