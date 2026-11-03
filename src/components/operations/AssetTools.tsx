import { refreshIngestParse } from "../../api/ingest";
import { useState } from "react";
import { confirmAssetReenable, requestAssetReenable } from "../../api/knowledge";
import { OperationPanel, useOperation } from "./OperationPanel";

function RestoreForm({ assetId, onChanged }: { assetId: string; onChanged: () => void }) {
  const [reason, setReason] = useState("");
  const [target, setTarget] = useState<"active" | "needs_update">("needs_update");
  const [confirming, setConfirming] = useState(false);
  const operation = useOperation();
  return (
    <div className="operation-form">
      <p>
        登记申请只留下恢复意向记录；确认恢复才会改变资料状态。已被新版替代的资料需先处理替代关系。
      </p>
      <label>
        恢复原因
        <textarea
          rows={3}
          value={reason}
          disabled={operation.busy}
          onChange={(event) => {
            setReason(event.target.value);
            setConfirming(false);
          }}
        />
      </label>
      <label>
        恢复后的状态
        <select
          value={target}
          disabled={operation.busy}
          onChange={(event) => {
            setTarget(event.target.value as typeof target);
            setConfirming(false);
          }}
        >
          <option value="needs_update">待更新</option>
          <option value="active">正常使用</option>
        </select>
      </label>
      <div className="operation-actions">
        {!confirming ? (
          <>
            <button
              className="btn-small"
              disabled={!reason.trim() || operation.busy}
              onClick={() =>
                void operation.run(async () => {
                  await requestAssetReenable(assetId, reason.trim(), target);
                  return "已登记恢复申请，资料仍处于归档状态。";
                })
              }
            >
              登记恢复申请
            </button>
            <button
              className="btn-small"
              disabled={!reason.trim() || operation.busy}
              onClick={() => setConfirming(true)}
            >
              恢复使用…
            </button>
          </>
        ) : (
          <>
            <button
              className="btn-small"
              disabled={operation.busy}
              onClick={() =>
                void operation.run(async () => {
                  await confirmAssetReenable(assetId, reason.trim(), target);
                  onChanged();
                  return "资料已恢复。";
                })
              }
            >
              {operation.busy ? "恢复中…" : "确认恢复"}
            </button>
            <button
              className="btn-small"
              disabled={operation.busy}
              onClick={() => setConfirming(false)}
            >
              取消
            </button>
          </>
        )}
      </div>
      {operation.feedback}
    </div>
  );
}
export function RestoreAssetButton(props: { assetId: string; onChanged: () => void }) {
  return (
    <OperationPanel label="恢复归档资料">
      <RestoreForm {...props} />
    </OperationPanel>
  );
}
export function RefreshParseButton({ taskId }: { taskId: string }) {
  const operation = useOperation();
  const labels: Record<string, string> = {
    completed: "解析完成",
    failed: "解析失败",
    pending: "等待解析",
    processing: "解析中",
    duplicate: "重复资料",
  };
  return (
    <div className="operation-content">
      <button
        className="btn-small"
        disabled={operation.busy}
        onClick={() =>
          void operation.run(async () => {
            const result = await refreshIngestParse(taskId);
            return result.parse_status
              ? `当前解析状态：${labels[result.parse_status] ?? result.parse_status}。此操作仅同步状态，不重新解析。`
              : "当前尚无可同步的解析结果。";
          })
        }
      >
        {operation.busy ? "正在同步…" : "同步解析状态"}
      </button>
      {operation.feedback}
    </div>
  );
}
