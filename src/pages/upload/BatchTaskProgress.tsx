export type BatchTaskState = "waiting" | "processing" | "success" | "failed";

const progressByState: Record<BatchTaskState, number> = {
  waiting: 0,
  processing: 50,
  success: 100,
  failed: 100,
};

const labelByState: Record<BatchTaskState, string> = {
  waiting: "等待",
  processing: "处理中",
  success: "成功",
  failed: "失败",
};

export default function BatchTaskProgress({ state }: { state: BatchTaskState }) {
  const label = labelByState[state];
  return (
    <span className={`upload77-batch-progress is-${state}`}>
      <progress aria-label={`批量确认进度：${label}`} max={100} value={progressByState[state]} />
      <span className="upload77-batch-state" role="status">
        {label}
      </span>
    </span>
  );
}
