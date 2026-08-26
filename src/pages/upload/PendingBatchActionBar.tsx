type PendingBatchActionBarProps = {
  confirmCount: number;
  rejectCount: number;
  busy: boolean;
  operation: "confirm" | "reject" | "delete" | null;
  onConfirm: () => void;
  onReject: () => void;
};

export default function PendingBatchActionBar({
  confirmCount,
  rejectCount,
  busy,
  operation,
  onConfirm,
  onReject,
}: PendingBatchActionBarProps) {
  return (
    <div className="upload77-batch-actions">
      {confirmCount > 0 && (
        <button className="btn-primary" disabled={busy} onClick={onConfirm} type="button">
          {busy && operation === "confirm" ? "正在逐条确认" : `批量确认入库（${confirmCount}）`}
        </button>
      )}
      {rejectCount > 0 && (
        <button
          className="btn-secondary upload77-batch-reject"
          disabled={busy}
          onClick={onReject}
          type="button"
        >
          批量拒绝入库（{rejectCount}）
        </button>
      )}
    </div>
  );
}
