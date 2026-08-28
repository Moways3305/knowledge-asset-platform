import { useCallback, useEffect, useRef, useState } from "react";
import { fetchPeople } from "../api/admin";
import { ApiError } from "../api/http";
import { createProject } from "../api/project";
import type { PersonDTO } from "../types/people";
import type { ProjectCreateResponseDTO } from "../types/project";
import "./CreateProjectModal.css";

export default function CreateProjectModal({
  open,
  onClose,
  onCreated,
}: {
  open: boolean;
  onClose: () => void;
  onCreated: (project: ProjectCreateResponseDTO) => void | Promise<void>;
}) {
  const [name, setName] = useState("");
  const [client, setClient] = useState("");
  const [managerId, setManagerId] = useState("");
  const [projectCode, setProjectCode] = useState("");
  const [defaultConfidentiality, setDefaultConfidentiality] = useState("L2");
  const [candidates, setCandidates] = useState<PersonDTO[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const nameInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!open) return;
    setName("");
    setClient("");
    setManagerId("");
    setProjectCode("");
    setDefaultConfidentiality("L2");
    setCandidates([]);
    setError(null);
    setBusy(false);
    const focusTimer = window.setTimeout(() => nameInputRef.current?.focus(), 0);
    void fetchPeople()
      .then((response) => setCandidates(response.items))
      .catch((nextError) => {
        setError(
          nextError instanceof ApiError && nextError.status === 403
            ? "当前身份无权加载用户列表"
            : "用户列表加载失败，请稍后重试",
        );
      });
    return () => window.clearTimeout(focusTimer);
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !busy) onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [busy, onClose, open]);

  const submit = useCallback(async () => {
    if (!name.trim() || !managerId || !projectCode.trim()) {
      setError("请填写项目名称、项目代码并选择项目经理");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const created = await createProject({
        name: name.trim(),
        client_name: client.trim() || null,
        project_manager_user_id: managerId,
        project_code: projectCode.trim().toUpperCase(),
        project_code_active: true,
        naming_default_confidentiality: defaultConfidentiality,
      });
      await onCreated(created);
    } catch (nextError) {
      setError(
        nextError instanceof ApiError && nextError.status === 403
          ? "当前身份无权创建项目"
          : "项目创建失败，请稍后重试",
      );
    } finally {
      setBusy(false);
    }
  }, [client, defaultConfidentiality, managerId, name, onCreated, projectCode]);

  if (!open) return null;
  return (
    <div className="project78-modal-overlay" role="dialog" aria-modal="true" aria-label="新建项目">
      <div className="project78-modal">
        <div className="project78-modal-head">
          <h3>新建项目</h3>
          <button
            type="button"
            className="project78-modal-close"
            onClick={onClose}
            aria-label="关闭"
          >
            ×
          </button>
        </div>
        {error && <div className="project78-modal-error">{error}</div>}
        <div className="project78-modal-body">
          <label className="project78-modal-field">
            <span>项目名称</span>
            <input
              ref={nameInputRef}
              type="text"
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="输入项目名称"
              autoComplete="off"
            />
          </label>
          <label className="project78-modal-field">
            <span>客户名称（可选）</span>
            <input
              type="text"
              value={client}
              onChange={(event) => setClient(event.target.value)}
              placeholder="输入客户名称"
              autoComplete="off"
            />
          </label>
          <label className="project78-modal-field">
            <span>项目经理</span>
            <select value={managerId} onChange={(event) => setManagerId(event.target.value)}>
              <option value="">请选择项目经理</option>
              {candidates.map((person) => (
                <option key={person.user_id} value={person.user_id}>
                  {person.name}
                </option>
              ))}
            </select>
          </label>
          <label className="project78-modal-field">
            <span>项目代码</span>
            <input
              type="text"
              value={projectCode}
              maxLength={20}
              onChange={(event) => setProjectCode(event.target.value.toUpperCase())}
              placeholder="如 BW-2601"
              autoComplete="off"
            />
            <small>创建后立即启用，作为规范命名必需项。</small>
          </label>
          <label className="project78-modal-field">
            <span>默认保密级别</span>
            <select
              value={defaultConfidentiality}
              onChange={(event) => setDefaultConfidentiality(event.target.value)}
            >
              {["L1", "L2", "L3", "L4", "L5"].map((level) => (
                <option key={level} value={level}>
                  {level}
                </option>
              ))}
            </select>
          </label>
        </div>
        <div className="project78-modal-actions">
          <button
            type="button"
            className="product-button is-primary"
            disabled={busy || !name.trim() || !managerId || !projectCode.trim()}
            onClick={() => void submit()}
          >
            {busy ? "创建中…" : "创建项目"}
          </button>
          <button
            type="button"
            className="product-button is-secondary"
            disabled={busy}
            onClick={onClose}
          >
            取消
          </button>
        </div>
      </div>
    </div>
  );
}
