import { useId, useRef, useState, type FormEvent } from "react";
import { FolderPlus } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { apiPost } from "../api/http";
import { fetchKnowledgeDirectories } from "../api/knowledge";
import type { KnowledgeDirectoryDTO } from "../types/knowledge";
import TaskModal from "./TaskModal";
import "./CreateKnowledgeDirectoryButton.css";

export default function CreateKnowledgeDirectoryButton({
  scope,
  projectId,
  initialParent,
}: {
  scope: "company" | "project";
  projectId?: string;
  initialParent?: string;
}) {
  const navigate = useNavigate();
  const id = useId();
  const [open, setOpen] = useState(false);
  const [parents, setParents] = useState<KnowledgeDirectoryDTO[]>([]);
  const [parent, setParent] = useState("");
  const [name, setName] = useState("");
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const request = useRef(0);

  const close = () => {
    if (busy) return;
    request.current += 1;
    setOpen(false);
  };
  const load = async () => {
    const current = ++request.current;
    setLoading(true);
    setError("");
    try {
      const rows = await fetchKnowledgeDirectories({ scope, projectId });
      if (current !== request.current) return;
      const choices = rows.filter(
        (row) => !row.parent_key && row.directory_key !== "project.unclassified",
      );
      setParents(choices);
      setParent(
        choices.some((row) => row.directory_key === initialParent)
          ? initialParent!
          : (choices[0]?.directory_key ?? ""),
      );
    } catch {
      if (current === request.current) setError("分类加载失败，请重试。");
    } finally {
      if (current === request.current) setLoading(false);
    }
  };
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (busy || loading || !name.trim() || !parent) return;
    setBusy(true);
    setError("");
    try {
      const created = await apiPost<{ directory_key: string }>("/api/v1/knowledge/directories", {
        scope,
        project_id: scope === "project" ? projectId : null,
        parent_key: parent,
        display_name: name.trim(),
      });
      setOpen(false);
      const query = new URLSearchParams({ scope, directory_key: created.directory_key });
      if (projectId) query.set("project_id", projectId);
      navigate(`/knowledge?${query}`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "目录创建失败，请重试。");
    } finally {
      setBusy(false);
    }
  };
  return (
    <>
      <button
        type="button"
        className="product-button is-secondary"
        onClick={() => {
          setName("");
          setParents([]);
          setParent("");
          setOpen(true);
          void load();
        }}
      >
        <FolderPlus size={16} aria-hidden="true" />
        新建目录
      </button>
      <TaskModal
        open={open}
        title="新建三级目录"
        size="small"
        portal
        busy={busy}
        onClose={close}
        description="选择标准分类，创建后即可使用。不会发布目录治理中的其他草稿。"
      >
        <form className="knowledge-directory-create" onSubmit={submit}>
          <label htmlFor={`${id}-parent`}>所属分类</label>
          <select
            id={`${id}-parent`}
            value={parent}
            disabled={loading || busy}
            required
            onChange={(event) => setParent(event.target.value)}
          >
            <option value="">{loading ? "正在加载分类…" : "请选择分类"}</option>
            {parents.map((row) => (
              <option key={row.directory_key} value={row.directory_key}>
                {row.name}
              </option>
            ))}
          </select>
          <label htmlFor={`${id}-name`}>目录名称</label>
          <input
            id={`${id}-name`}
            value={name}
            onChange={(event) => setName(event.target.value)}
            maxLength={80}
            required
            disabled={busy}
            autoComplete="off"
          />
          <p>新目录沿用所属分类的默认密级；资料仍按原有权限控制。</p>
          {error && <div role="alert">{error}</div>}
          {error && parents.length === 0 && (
            <button
              type="button"
              className="product-button is-secondary"
              onClick={() => void load()}
            >
              重新加载分类
            </button>
          )}
          <div className="knowledge-directory-create-actions">
            <button
              type="button"
              className="product-button is-secondary"
              onClick={close}
              disabled={busy}
            >
              取消
            </button>
            <button
              type="submit"
              className="product-button is-primary"
              disabled={busy || loading || !parent || !name.trim()}
            >
              {busy ? "创建中…" : "创建目录"}
            </button>
          </div>
        </form>
      </TaskModal>
    </>
  );
}
