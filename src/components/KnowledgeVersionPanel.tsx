import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError } from "../api/http";
import {
  compareVersions,
  fetchVersionHistory,
  uploadVersion,
  type VersionHistory,
  type VersionComparison,
} from "../api/knowledgeVersions";
import { fetchTrust, replaceTrust } from "../api/knowledgeTrust";
import { formatBeijingTime } from "../utils/time";
import { ActionGroup } from "./ActionLayout";
import TaskModal from "./TaskModal";
import "./KnowledgeVersionPanel.css";

const statusLabel: Record<string, string> = {
  processing: "处理中",
  pending_confirmation: "待确认入库",
  waiting_review: "待审批",
  completed: "已入库，待核查替代",
  failed: "处理失败",
  cancelled: "已取消",
  active: "有效",
  archived: "已归档",
  superseded: "已替代",
  needs_update: "需更新",
};
const message = (error: unknown) =>
  error instanceof ApiError ? error.message : "操作失败，请刷新状态后重试。";

export default function KnowledgeVersionPanel({
  assetId,
  onReplaced,
  onHistoryLoaded,
}: {
  assetId: string;
  onReplaced?: () => void;
  onHistoryLoaded?: (history: VersionHistory) => void;
}) {
  const historyLoadedRef = useRef(onHistoryLoaded);
  historyLoadedRef.current = onHistoryLoaded;
  const [state, setState] = useState<VersionHistory | null>(null);
  const [open, setOpen] = useState<"history" | "upload" | "replace" | "snapshot" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [version, setVersion] = useState("");
  const [taskId, setTaskId] = useState<string | null>(null);
  const [left, setLeft] = useState("");
  const [right, setRight] = useState("");
  const [diff, setDiff] = useState<VersionComparison | null>(null);
  const [snapshot, setSnapshot] = useState<VersionComparison["left"] | null>(null);
  const [candidate, setCandidate] = useState<{ id: string; stamp: string } | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [reason, setReason] = useState("");
  useEffect(() => {
    let active = true;
    setState(null);
    setOpen(null);
    setError(null);
    setTaskId(null);
    setDiff(null);
    setFile(null);
    fetchVersionHistory(assetId)
      .then((value) => {
        if (active) {
          setState(value);
          historyLoadedRef.current?.(value);
          setVersion(value.suggested_version);
        }
      })
      .catch((failure) => {
        if (active && (!(failure instanceof ApiError) || failure.status !== 404))
          setError("版本信息暂不可用，请重试。");
      });
    return () => {
      active = false;
    };
  }, [assetId]);
  async function refresh() {
    const value = await fetchVersionHistory(assetId);
    setState(value);
    historyLoadedRef.current?.(value);
    return value;
  }
  if (!state)
    return error ? (
      <div className="knowledge-versions">
        <p role="alert">{error}</p>
        <button
          className="btn-secondary"
          onClick={() => {
            setError(null);
            void refresh().catch(() => setError("版本信息暂不可用，请重试。"));
          }}
        >
          重试版本信息
        </button>
      </div>
    ) : null;
  return (
    <section className="knowledge-versions" aria-label="资料版本管理">
      <h2>版本管理</h2>
      {state.current_asset_id && state.current_asset_id !== assetId && (
        <p className="knowledge-version-replaced">
          此版本不是当前已确认使用的版本。
          <Link to={`/knowledge/${state.current_asset_id}`}>查看当前版本</Link>
        </p>
      )}
      <ActionGroup className="knowledge-version-actions" label="版本操作">
        {state.can_update && (
          <button
            type="button"
            className="btn-secondary"
            onClick={() => {
              setError(null);
              setTaskId(null);
              setFile(null);
              setOpen("upload");
            }}
          >
            更新这份资料
          </button>
        )}
        <button
          type="button"
          className="btn-secondary"
          onClick={() => {
            setError(null);
            setOpen("history");
            void refresh().catch((e) => setError(message(e)));
          }}
        >
          版本历史与差异
        </button>
      </ActionGroup>
      <TaskModal
        open={open === "upload"}
        title="更新这份资料"
        description="新版沿用原库、资料区、目录和密级。上传不会归档旧版；完成入库和复核后再确认替代。"
        busy={busy}
        onClose={() => setOpen(null)}
      >
        <div className="knowledge-version-form">
          <label>
            新版本号
            <input
              value={version}
              maxLength={20}
              onChange={(e) => setVersion(e.target.value)}
              placeholder="例如 V2"
              disabled={busy || Boolean(taskId)}
            />
          </label>
          <label>
            选择新版原文件
            <input
              type="file"
              disabled={busy || Boolean(taskId)}
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            />
          </label>
          {error && <p role="alert">{error}</p>}
          {taskId ? (
            <p role="status">
              新版上传任务已创建。
              <Link to={`/upload?source=local&task_id=${taskId}`}>继续处理并确认入库</Link>
              。旧版保持有效，完成后回原资料核查替代。
            </p>
          ) : (
            <button
              type="button"
              className="btn-primary"
              disabled={busy || !file || !version.trim()}
              onClick={async () => {
                if (!file) return;
                setBusy(true);
                setError(null);
                try {
                  const result = await uploadVersion(assetId, file, state.updated_at, version);
                  setTaskId(result.ingest_task_id);
                  await refresh();
                } catch (e) {
                  setError(message(e));
                } finally {
                  setBusy(false);
                }
              }}
            >
              {busy ? "正在上传…" : "上传关联新版"}
            </button>
          )}
        </div>
      </TaskModal>
      <TaskModal
        open={open === "history"}
        title="版本历史与差异"
        description="当前版本以已确认替代关系为准；下方比较仅包含可见摘要与版本元信息，不是原文件全文差异。"
        size="large"
        onClose={() => setOpen(null)}
        busy={busy}
      >
        {state.truncated && <p role="status">历史较多，本次显示部分记录。</p>}
        <ul className="knowledge-version-list">
          {state.items.map((item) => (
            <li key={item.version_id}>
              <div>
                <strong>{item.version}</strong>{" "}
                <span>
                  {item.is_current ? "当前版本" : (statusLabel[item.status] ?? item.status)}
                </span>
                <p>{item.title}</p>
                <small>{formatBeijingTime(item.created_at)}</small>
              </div>
              <div>
                <button
                  className="btn-secondary"
                  disabled={busy}
                  onClick={async () => {
                    setBusy(true);
                    setError(null);
                    try {
                      const result = await compareVersions(
                        assetId,
                        item.version_id,
                        item.version_id,
                      );
                      setSnapshot(result.left);
                      setOpen("snapshot");
                    } catch (failure) {
                      setError(message(failure));
                    } finally {
                      setBusy(false);
                    }
                  }}
                >
                  查看版本摘要
                </button>
                {item.is_current && <Link to={`/knowledge/${item.asset_id}`}>查看当前资料</Link>}
              </div>
            </li>
          ))}
        </ul>
        {state.can_update && state.updates.length > 0 && (
          <div>
            <h3>本资料的新版本任务</h3>
            <ul className="knowledge-version-list">
              {state.updates.map((item) => (
                <li key={item.task_id}>
                  <div>
                    {item.version} · {statusLabel[item.status] ?? item.status}
                  </div>
                  <div>
                    {item.result_asset_id ? (
                      <>
                        <Link to={`/knowledge/${item.result_asset_id}`}>查看并复核新版</Link>
                        {item.can_replace && (
                          <button
                            type="button"
                            className="btn-secondary"
                            disabled={busy}
                            onClick={async () => {
                              setBusy(true);
                              try {
                                const target = await fetchTrust(item.result_asset_id!);
                                setCandidate({ id: target.asset_id, stamp: target.updated_at });
                                setConfirmed(false);
                                setReason("");
                                setError(null);
                                setOpen("replace");
                              } catch (e) {
                                setError(message(e));
                              } finally {
                                setBusy(false);
                              }
                            }}
                          >
                            确认替代
                          </button>
                        )}
                      </>
                    ) : (
                      item.status !== "cancelled" && (
                        <Link to={`/upload?source=local&task_id=${item.task_id}`}>继续处理</Link>
                      )
                    )}
                  </div>
                </li>
              ))}
            </ul>
          </div>
        )}
        <div className="knowledge-version-compare">
          <h3>比较两个版本</h3>
          <label>
            原版本
            <select
              aria-label="原版本"
              value={left}
              onChange={(e) => {
                setLeft(e.target.value);
                setDiff(null);
              }}
            >
              <option value="">请选择</option>
              {state.items.map((item) => (
                <option key={item.version_id} value={item.version_id}>
                  {item.version} · {item.title}
                </option>
              ))}
            </select>
          </label>
          <label>
            新版本
            <select
              aria-label="新版本"
              value={right}
              onChange={(e) => {
                setRight(e.target.value);
                setDiff(null);
              }}
            >
              <option value="">请选择</option>
              {state.items.map((item) => (
                <option key={item.version_id} value={item.version_id}>
                  {item.version} · {item.title}
                </option>
              ))}
            </select>
          </label>
          <button
            className="btn-secondary"
            disabled={busy || !left || !right || left === right}
            onClick={async () => {
              setBusy(true);
              setError(null);
              try {
                setDiff(await compareVersions(assetId, left, right));
              } catch (e) {
                setError(message(e));
              } finally {
                setBusy(false);
              }
            }}
          >
            查看差异
          </button>
        </div>
        {diff && (
          <div className="knowledge-version-diff">
            <p>{diff.scope}</p>
            {(["version", "directory", "summary"] as const).map((key) => (
              <div key={key}>
                <h4>
                  {{ version: "版本", directory: "正式目录", summary: "可见摘要" }[key]} ·{" "}
                  {diff.changed_fields.includes(key) ? "有变化" : "无可见变化"}
                </h4>
                <div className="knowledge-version-columns">
                  <div>
                    <strong>原版本</strong>
                    <p>{diff.left[key] ?? "暂无可见内容"}</p>
                  </div>
                  <div>
                    <strong>新版本</strong>
                    <p>{diff.right[key] ?? "暂无可见内容"}</p>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
        {error && <p role="alert">{error}</p>}
      </TaskModal>
      <TaskModal
        open={open === "replace"}
        title="确认新版替代旧版"
        description="旧版将归档并退出默认检索与问答，原文件及版本历史保留。新版必须已复核；权限和并发冲突由服务端再次校验。"
        onClose={() => setOpen(null)}
        busy={busy}
      >
        <div className="knowledge-version-form">
          <label>
            替代原因
            <textarea value={reason} maxLength={1000} onChange={(e) => setReason(e.target.value)} />
          </label>
          <label>
            <input
              type="checkbox"
              checked={confirmed}
              onChange={(e) => setConfirmed(e.target.checked)}
            />
            我已核对新版，确认归档旧版
          </label>
          {error && <p role="alert">{error}</p>}
          <button
            className="btn-primary"
            disabled={busy || !confirmed || !reason.trim() || !candidate}
            onClick={async () => {
              if (!candidate) return;
              setBusy(true);
              setError(null);
              try {
                await replaceTrust(assetId, {
                  expected_updated_at: state.updated_at,
                  expected_replacement_updated_at: candidate.stamp,
                  replacement_asset_id: candidate.id,
                  confirm_archive: true,
                  reason: reason.trim(),
                });
                await refresh();
                setOpen("history");
                onReplaced?.();
              } catch (e) {
                setError(message(e));
              } finally {
                setBusy(false);
              }
            }}
          >
            确认替代并归档旧版
          </button>
        </div>
      </TaskModal>
      <TaskModal
        open={open === "snapshot"}
        title="版本摘要与元信息"
        description="这是所选版本的可见摘要快照，不是原文件预览；原文授权仍按原有规则办理。"
        onClose={() => setOpen("history")}
      >
        {snapshot && (
          <div>
            <p>版本：{snapshot.version}</p>
            <p>正式目录：{snapshot.directory ?? "未记录"}</p>
            <h3>可见摘要</h3>
            <p style={{ whiteSpace: "pre-wrap" }}>
              {snapshot.summary ?? "当前没有可见摘要，可能尚未生成或权限不足。"}
            </p>
            <button className="btn-secondary" onClick={() => setOpen("history")}>
              返回版本历史
            </button>
          </div>
        )}
      </TaskModal>
    </section>
  );
}
