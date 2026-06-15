import { useEffect, useState } from "react";
import { ApiError } from "../../api/http";
import { createProject } from "../../api/project";
import { fetchWecomScanOwnerOptions } from "../../api/admin";
import type { ProjectCreateResponseDTO } from "../../types/project";
import type { WecomOwnerOptionDTO } from "../../types/wecom";
import { useFormState } from "../../hooks/useFormState";
import ConfirmDialog from "../../components/ConfirmDialog";
import FormField from "../../components/FormField";

// 新建项目知识库模态。自包含表单态 + 创建调用：仅 boss / 咨询总监可见入口。
// 创建真实 projects + active project_manager；候选人来自真实后端 active 业务用户。
interface CreateProjectModalProps {
  open: boolean;
  onClose: () => void;
  onCreated: (project: ProjectCreateResponseDTO) => void;
}

export default function CreateProjectModal({ open, onClose, onCreated }: CreateProjectModalProps) {
  const { values, set, reset } = useFormState({ name: "", client: "", pm: "", coach: "" });
  const [ownerOptions, setOwnerOptions] = useState<WecomOwnerOptionDTO[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // 打开时重置表单并按需加载业务用户候选（项目经理 / 辅导老师）。
  useEffect(() => {
    if (!open) return;
    reset();
    setError(null);
    fetchWecomScanOwnerOptions()
      .then((d) => setOwnerOptions(d.items))
      .catch(() => setOwnerOptions([]));
  }, [open, reset]);

  const handleCreate = async () => {
    setError(null);
    if (!values.name.trim()) { setError("请填写项目名称"); return; }
    if (!values.pm) { setError("请选择项目经理"); return; }
    setBusy(true);
    try {
      const created = await createProject({
        name: values.name.trim(),
        client_name: values.client.trim() || null,
        project_manager_user_id: values.pm,
        coach_user_id: values.coach || null,
        lifecycle_route_key: "route_A",
      });
      onCreated(created);
    } catch (e) {
      setError(e instanceof ApiError ? `${e.message}（${e.deniedReason ?? e.status}）` : "创建项目失败");
    } finally {
      setBusy(false);
    }
  };

  return (
    <ConfirmDialog
      open={open}
      title="新建项目知识库"
      description="创建真实项目知识空间，并指定项目经理（自动建立 active 成员关系）。项目知识库随项目存在，资料 / 资产在同一库内用 zone 区分。"
      confirmText="创建项目"
      busyText="创建中…"
      busy={busy}
      error={error}
      onConfirm={() => void handleCreate()}
      onCancel={onClose}
    >
      <FormField label="项目名称">
        <input value={values.name} onChange={(e) => set("name", e.target.value)} maxLength={200} placeholder="如：某客户数字化转型项目" />
      </FormField>
      <FormField label="客户名称（可选）">
        <input value={values.client} onChange={(e) => set("client", e.target.value)} maxLength={200} />
      </FormField>
      <FormField label="项目经理">
        <select value={values.pm} onChange={(e) => set("pm", e.target.value)}>
          <option value="">请选择项目经理…</option>
          {ownerOptions.map((o) => (
            <option key={o.user_id} value={o.user_id}>{o.name}{o.role_label ? `（${o.role_label}）` : ""}</option>
          ))}
        </select>
      </FormField>
      <FormField label="辅导老师（可选）">
        <select value={values.coach} onChange={(e) => set("coach", e.target.value)}>
          <option value="">不指定</option>
          {ownerOptions.filter((o) => o.user_id !== values.pm).map((o) => (
            <option key={o.user_id} value={o.user_id}>{o.name}{o.role_label ? `（${o.role_label}）` : ""}</option>
          ))}
        </select>
      </FormField>
      <p className="kl-modal-hint">生命周期路线默认完整路线（route_A）。候选人来自真实后端 active 业务用户。</p>
    </ConfirmDialog>
  );
}
