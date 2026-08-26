import { useRef, useState } from "react";
import type {
  IngestAiResultDTO,
  IngestAiReviewDraftDTO,
  PendingIngestItemDTO,
} from "../../types/ingest";
import {
  commandErrorMatches,
  commandErrorMessage,
  fetchIngestAiResult,
  retryIngestTask,
} from "./pendingBatchCommands";

export function usePendingBatchAiReview() {
  const runRef = useRef(0);
  const [task, setTask] = useState<PendingIngestItemDTO | null>(null);
  const [result, setResult] = useState<IngestAiResultDTO | null>(null);
  const [form, setForm] = useState<IngestAiReviewDraftDTO | null>(null);
  const [drafts, setDrafts] = useState<Record<string, IngestAiReviewDraftDTO>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const open = async (nextTask: PendingIngestItemDTO, retry = false) => {
    const runId = ++runRef.current;
    setTask(nextTask);
    setBusy(true);
    setError(null);
    try {
      if (retry) await retryIngestTask(nextTask.id);
      const nextResult = await fetchIngestAiResult(nextTask.id);
      if (runRef.current !== runId) return;
      setResult(nextResult);
      setForm(
        drafts[nextTask.id] ?? {
          title: nextResult.suggested_title ?? "",
          one_liner: nextResult.suggested_one_liner ?? "",
          summary: nextResult.suggested_summary ?? nextResult.summary ?? "",
          key_points: nextResult.suggested_key_points?.filter(Boolean) ?? [],
          tags: nextResult.suggested_tags?.filter(Boolean) ?? [],
        },
      );
    } catch (caught) {
      if (runRef.current !== runId) return;
      setResult(null);
      setForm(drafts[nextTask.id] ?? null);
      setError(
        commandErrorMatches(caught, { status: 403 })
          ? "当前身份无权查看这条资料的 AI 提取结果。"
          : commandErrorMessage(caught, "AI 提取结果暂时无法加载，请刷新重试。"),
      );
    } finally {
      if (runRef.current === runId) setBusy(false);
    }
  };

  const cancel = () => {
    ++runRef.current;
    setTask(null);
  };

  const saveDraft = (): { taskId: string; draft: IngestAiReviewDraftDTO } | null => {
    if (!task || !form) return null;
    const draft = {
      ...form,
      title: form.title.trim(),
      one_liner: form.one_liner.trim(),
      summary: form.summary.trim(),
      key_points: form.key_points.map((item) => item.trim()).filter(Boolean),
      tags: form.tags.map((item) => item.trim()).filter(Boolean),
    };
    setDrafts((current) => ({ ...current, [task.id]: draft }));
    const saved = { taskId: task.id, draft };
    setTask(null);
    return saved;
  };

  const reset = () => {
    ++runRef.current;
    setTask(null);
    setResult(null);
    setForm(null);
    setDrafts({});
    setError(null);
    setBusy(false);
  };

  return { task, result, form, setForm, drafts, busy, error, open, cancel, saveDraft, reset };
}

export type PendingBatchAiReviewController = ReturnType<typeof usePendingBatchAiReview>;
