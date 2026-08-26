import DetailDrawer from "../../components/DetailDrawer";
import type { PendingBatchAiReviewController } from "./usePendingBatchAiReview";

type Props = {
  review: PendingBatchAiReviewController;
  onSave: () => void;
};

export default function PendingBatchAiReviewDrawer({ review, onSave }: Props) {
  const { task, result, form, setForm, busy, error } = review;

  return (
    <DetailDrawer
      open={task !== null}
      title="AI 提取核对"
      description={task?.source_file_name}
      busy={busy}
      onClose={() => {
        if (!busy) review.cancel();
      }}
      footer={
        <>
          <button className="btn-secondary" disabled={busy} onClick={review.cancel} type="button">
            取消
          </button>
          <button
            className="btn-primary"
            disabled={busy || !form?.title.trim() || !form?.summary.trim()}
            onClick={onSave}
            type="button"
          >
            保存本条修改
          </button>
        </>
      }
    >
      {busy ? (
        <p role="status">正在读取 AI 提取结果…</p>
      ) : error ? (
        <div role="alert">
          <p>{error}</p>
          <button
            className="btn-secondary"
            onClick={() => task && void review.open(task)}
            type="button"
          >
            刷新
          </button>
        </div>
      ) : result?.status === "processing" ? (
        <div role="status">
          <p>AI 提取仍在处理中，完成前不会提交入库。</p>
          <button
            className="btn-secondary"
            onClick={() => task && void review.open(task)}
            type="button"
          >
            刷新状态
          </button>
        </div>
      ) : result?.status === "failed" ? (
        <div role="alert">
          <p>AI 提取未完成，可重试生成；当前资料不会因此入库。</p>
          <button
            className="btn-secondary"
            onClick={() => task && void review.open(task, true)}
            type="button"
          >
            重试生成
          </button>
        </div>
      ) : form ? (
        <div className="upload77-ai-review-form">
          <label>
            <span>建议标题</span>
            <input
              value={form.title}
              onChange={(event) =>
                setForm((current) =>
                  current ? { ...current, title: event.target.value } : current,
                )
              }
            />
          </label>
          <label>
            <span>一句话摘要</span>
            <textarea
              rows={2}
              value={form.one_liner}
              onChange={(event) =>
                setForm((current) =>
                  current ? { ...current, one_liner: event.target.value } : current,
                )
              }
            />
          </label>
          <label>
            <span>详细摘要</span>
            <textarea
              rows={8}
              value={form.summary}
              onChange={(event) =>
                setForm((current) =>
                  current ? { ...current, summary: event.target.value } : current,
                )
              }
            />
          </label>
          <label>
            <span>关键点（每行一项）</span>
            <textarea
              rows={5}
              value={form.key_points.join("\n")}
              onChange={(event) =>
                setForm((current) =>
                  current ? { ...current, key_points: event.target.value.split("\n") } : current,
                )
              }
            />
          </label>
          <label>
            <span>标签（用逗号分隔）</span>
            <input
              value={form.tags.join("，")}
              onChange={(event) =>
                setForm((current) =>
                  current ? { ...current, tags: event.target.value.split(/[,，]/) } : current,
                )
              }
            />
          </label>
          <div role="status">
            生成状态：
            {result?.suggestion_generation_status === "generated"
              ? "已生成"
              : result?.suggestion_generation_status === "needs_correction"
                ? "需校正"
                : "需人工补齐"}
          </div>
        </div>
      ) : null}
    </DetailDrawer>
  );
}
