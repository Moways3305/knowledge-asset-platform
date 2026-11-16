import { useState } from "react";
import { Trash2 } from "lucide-react";
import {
  cancelAgentRun,
  deleteAgentRun,
  deleteAgentRuns,
  retryAgentRun,
  type ScanRun,
} from "../api/maintenanceAgent";
import { ApiError } from "../api/http";
import Button from "../components/Button";
import ConfirmDialog from "../components/ConfirmDialog";
import { formatBeijingTime } from "../utils/time";

const active = (run: ScanRun) => ["queued", "running"].includes(run.status);
const labels: Record<string, string> = {
  queued: "等待巡检",
  running: "巡检中",
  completed: "已完成",
  partial: "部分未完成",
  cancelled: "已取消",
  empty: "无检查对象",
};
const kind = (run: ScanRun) =>
  ({ incremental: "每日增量", recheck: "指定资料复检", retry: "未完成项重试" })[run.kind] ||
  "全面巡检";

export default function MaintenanceRunList({
  library,
  runs,
  onSelect,
  onChanged,
}: {
  library: string;
  runs: ScanRun[];
  onSelect: (id: string) => void;
  onChanged: (deleted: string[]) => void;
}) {
  const [selected, setSelected] = useState<string[]>([]);
  const [confirm, setConfirm] = useState<{ action: "delete" | "cancel"; ids: string[] } | null>(
    null,
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const removable = runs.filter((run) => !active(run)).map((run) => run.id);
  const picked = selected.filter((id) => removable.includes(id));
  const perform = async () => {
    if (!confirm || busy) return;
    setBusy(true);
    setError("");
    try {
      if (confirm.action === "cancel") await cancelAgentRun(library, confirm.ids[0]);
      else if (confirm.ids.length === 1) await deleteAgentRun(library, confirm.ids[0]);
      else await deleteAgentRuns(library, confirm.ids);
      const deleted = confirm.action === "delete" ? confirm.ids : [];
      setSelected([]);
      setConfirm(null);
      onChanged(deleted);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "操作未完成，请重试。");
    } finally {
      setBusy(false);
    }
  };
  const retry = async (id: string) => {
    setBusy(true);
    setError("");
    try {
      const run = await retryAgentRun(library, id);
      onChanged([]);
      onSelect(run.id);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "重试未提交，请稍后再试。");
    } finally {
      setBusy(false);
    }
  };
  return (
    <>
      <div className="agent-history-toolbar">
        <label className="agent-checkbox">
          <input
            type="checkbox"
            aria-label="选择本页已结束记录"
            checked={removable.length > 0 && picked.length === removable.length}
            disabled={!removable.length || busy}
            onChange={(e) => setSelected(e.target.checked ? removable : [])}
          />
          {picked.length ? `已选择 ${picked.length} 条` : "选择已结束记录"}
        </label>
        <Button
          size="small"
          icon={<Trash2 size={14} />}
          disabled={!picked.length || busy}
          onClick={() => {
            setError("");
            setConfirm({ action: "delete", ids: picked });
          }}
        >
          删除所选记录
        </Button>
      </div>
      {error && !confirm && <p role="alert">{error}</p>}
      <div className="agent-history-table-wrap">
        <table className="agent-history-table">
          <thead>
            <tr>
              <th aria-label="选择" />
              <th>巡检 / 提交时间</th>
              <th>状态</th>
              <th>处理进度</th>
              <th>未完成 / 跳过</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {runs.map((run) => {
              const processed = run.completed_count + run.incomplete_count + run.skipped_count;
              return (
                <tr key={run.id}>
                  <td>
                    <input
                      type="checkbox"
                      aria-label={`选择 ${formatBeijingTime(run.started_at)} 的巡检记录`}
                      disabled={active(run) || busy}
                      checked={picked.includes(run.id)}
                      onChange={(e) =>
                        setSelected(
                          e.target.checked
                            ? [...picked, run.id]
                            : picked.filter((id) => id !== run.id),
                        )
                      }
                    />
                  </td>
                  <td>
                    <strong>{kind(run)}</strong>
                    <time>{formatBeijingTime(run.started_at)}</time>
                  </td>
                  <td>
                    <span className={`agent-status agent-status-${run.status}`}>
                      {run.target_count === 0 && !active(run)
                        ? "无检查对象"
                        : labels[run.status] || run.status}
                    </span>
                  </td>
                  <td>
                    <span className="agent-history-count">
                      {processed.toLocaleString()} / {run.target_count.toLocaleString()}
                    </span>
                    <progress
                      aria-label="已处理资料"
                      value={processed}
                      max={Math.max(1, run.target_count)}
                    />
                    <small>
                      {run.target_count === 0
                        ? "未检查资料，详情中可核对范围"
                        : `完成检查 ${run.completed_count.toLocaleString()} 份`}
                    </small>
                  </td>
                  <td className="agent-history-count">
                    <span className={run.incomplete_count ? "agent-count-warning" : ""}>
                      {run.incomplete_count.toLocaleString()}
                    </span>{" "}
                    / {run.skipped_count.toLocaleString()}
                  </td>
                  <td>
                    <div className="agent-history-actions">
                      <Button
                        size="small"
                        aria-label="查看巡检详情"
                        onClick={() => onSelect(run.id)}
                      >
                        详情
                      </Button>
                      {run.can_retry && (
                        <Button size="small" disabled={busy} onClick={() => void retry(run.id)}>
                          重试未完成项
                        </Button>
                      )}
                      <Button
                        size="small"
                        disabled={busy}
                        onClick={() => {
                          setError("");
                          setConfirm({ action: active(run) ? "cancel" : "delete", ids: [run.id] });
                        }}
                      >
                        {active(run) ? "取消巡检" : "删除"}
                      </Button>
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <ConfirmDialog
        open={!!confirm}
        portal
        busy={busy}
        danger={confirm?.action === "delete"}
        title={confirm?.action === "cancel" ? "取消本轮巡检？" : "删除巡检记录？"}
        description={
          confirm?.action === "cancel"
            ? "停止后续检查，已完成的结果和已发现的维护待办保留。取消后可重试未完成项。"
            : `将删除 ${confirm?.ids.length || 0} 条记录及其巡检明细。知识资料、维护待办和巡检设置保留。`
        }
        confirmText={confirm?.action === "cancel" ? "确认取消巡检" : "确认删除记录"}
        error={error}
        errorDescription={error}
        onCancel={() => {
          if (!busy) {
            setConfirm(null);
            setError("");
          }
        }}
        onConfirm={() => void perform()}
      />
    </>
  );
}
