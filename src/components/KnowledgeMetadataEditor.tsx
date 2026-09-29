import { useState } from "react";
import {
  fetchKnowledgeDetail,
  fetchKnowledgeDirectories,
  updateKnowledgeMetadata,
} from "../api/knowledge";
import type { KnowledgeDetailVM, KnowledgeDirectoryDTO } from "../types/knowledge";
import TaskModal from "./TaskModal";
import "./KnowledgeMetadataEditor.css";

export default function KnowledgeMetadataEditor({
  asset,
  onSaved,
}: {
  asset: KnowledgeDetailVM;
  onSaved: () => void;
}) {
  const [editing, setEditing] = useState<KnowledgeDetailVM | null>(null);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [title, setTitle] = useState("");
  const [tags, setTags] = useState("");
  const [level, setLevel] = useState("");
  const [directory, setDirectory] = useState("");
  const [directories, setDirectories] = useState<KnowledgeDirectoryDTO[]>([]);
  const [directoryError, setDirectoryError] = useState(false);
  const [summary, setSummary] = useState("");
  const [reason, setReason] = useState("");
  const [confirmed, setConfirmed] = useState(false);

  if (!asset.access.canEditMetadata) return null;
  async function open() {
    setLoading(true);
    setError("");
    setMessage("");
    try {
      const current = await fetchKnowledgeDetail(asset.id);
      if (!current.access.canEditMetadata) throw new Error("当前已无编辑权限，请刷新资料");
      setTitle(current.title);
      setTags(current.tags.join("，"));
      setLevel(current.confidentialityLevel);
      setDirectory(current.directoryKey ?? "");
      setSummary("");
      setReason("");
      setConfirmed(false);
      setDirectories([]);
      setDirectoryError(false);
      setEditing(current);
      try {
        setDirectories(
          await fetchKnowledgeDirectories({
            scope: current.scope,
            projectId: current.projectId ?? undefined,
          }),
        );
      } catch {
        setDirectoryError(true);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "无法加载资料，请重试");
    } finally {
      setLoading(false);
    }
  }
  const downgrade = editing !== null && level < editing.confidentialityLevel;
  async function save() {
    if (!editing) return;
    const changes: Record<string, unknown> = {};
    if (title.trim() !== editing.title) changes.title = title.trim();
    const nextTags = [
      ...new Set(
        tags
          .split(/[,，\n]/)
          .map((t) => t.trim())
          .filter(Boolean),
      ),
    ];
    if (JSON.stringify(nextTags) !== JSON.stringify(editing.tags)) changes.tags = nextTags;
    if (level !== editing.confidentialityLevel) changes.confidentiality_level = level;
    if (directory && directory !== editing.directoryKey) changes.directory_key = directory;
    if (summary.trim()) changes.summary = summary.trim();
    if (!Object.keys(changes).length) {
      setError("尚未修改资料");
      return;
    }
    setBusy(true);
    setError("");
    try {
      await updateKnowledgeMetadata(editing.id, {
        ...changes,
        expected_updated_at: editing.metadataUpdatedAt,
        reason: reason.trim(),
        confirm_downgrade: confirmed,
      });
      setEditing(null);
      setMessage("资料已保存");
      onSaved();
    } catch (err) {
      setError(err instanceof Error ? err.message : "保存失败，请重试");
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="metadata-editor-host" onKeyDown={(event) => event.stopPropagation()}>
      <button
        type="button"
        className="product-button is-secondary"
        onClick={() => void open()}
        disabled={loading}
      >
        {loading ? "正在加载…" : "编辑资料"}
      </button>
      {message && <span role="status">{message}</span>}
      {!editing && error && <p role="alert">{error}</p>}
      <TaskModal
        open={editing !== null}
        title="编辑资料"
        description="修正资料信息，无需重新上传。原文、所属知识库和版本保持不变。"
        busy={busy}
        onClose={() => setEditing(null)}
        portal
        footer={
          <>
            <button
              type="button"
              className="product-button is-secondary"
              disabled={busy}
              onClick={() => setEditing(null)}
            >
              取消
            </button>
            <button
              type="submit"
              form="knowledge-metadata-form"
              className="product-button is-primary"
              disabled={
                busy || loading || !reason.trim() || !title.trim() || (downgrade && !confirmed)
              }
            >
              {busy ? "保存中…" : "保存修改"}
            </button>
          </>
        }
      >
        <form
          id="knowledge-metadata-form"
          className="metadata-editor"
          onSubmit={(e) => {
            e.preventDefault();
            void save();
          }}
        >
          <fieldset disabled={busy}>
            <label>
              资料标题
              <input
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                required
                maxLength={500}
              />
            </label>
            <label>
              正式目录
              <select
                value={directory}
                disabled={directoryError}
                onChange={(e) => setDirectory(e.target.value)}
              >
                <option value={editing?.directoryKey ?? ""}>
                  {editing?.directoryPath || "保持当前目录"}
                </option>
                {directories
                  .filter(
                    (d) =>
                      d.directory_key !== editing?.directoryKey &&
                      d.directory_key !== "personal.pending",
                  )
                  .map((d) => (
                    <option key={d.directory_key} value={d.directory_key}>
                      {d.display_path}
                    </option>
                  ))}
              </select>
            </label>
            {directoryError && (
              <p role="status">目录加载失败；仍可修改其他信息，当前目录保持不变。</p>
            )}
            <label>
              标签
              <input
                value={tags}
                onChange={(e) => setTags(e.target.value)}
                placeholder="用逗号分隔，最多 20 个"
              />
            </label>
            <label>
              保密等级
              <select
                value={level}
                onChange={(e) => {
                  setLevel(e.target.value);
                  setConfirmed(false);
                }}
              >
                {["L1 公开", "L2 内部参考", "L3 受限", "L4 商业秘密", "L5 严格商业秘密"].map(
                  (label) => (
                    <option key={label} value={label.slice(0, 2)}>
                      {label}
                    </option>
                  ),
                )}
              </select>
            </label>
            {editing && level !== editing.confidentialityLevel && (
              <p className="metadata-warning">
                保密等级变更后，旧预览凭证失效；提升等级还会撤销已有原文授权，需重新审批。AI
                使用设置不会自动放宽。
              </p>
            )}
            {downgrade && (
              <label className="metadata-confirm">
                <input
                  type="checkbox"
                  checked={confirmed}
                  onChange={(e) => setConfirmed(e.target.checked)}
                />
                我确认降低保密等级，理解这可能扩大检索、摘要和原文访问范围。
              </label>
            )}
            <label>
              更正摘要（选填）
              <textarea
                value={summary}
                onChange={(e) => setSummary(e.target.value)}
                rows={5}
                maxLength={10000}
                placeholder="留空保留现有摘要。填写后替换摘要及旧要点，按保密等级重新脱敏。"
              />
            </label>
            <label>
              修改原因
              <textarea
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                required
                maxLength={500}
                rows={2}
                placeholder="说明修改依据，将保留在审计记录中"
              />
            </label>
          </fieldset>
          {error && (
            <p role="alert" className="metadata-warning">
              {error}
            </p>
          )}
        </form>
      </TaskModal>
    </div>
  );
}
