import { useEffect, useMemo, useState } from "react";
import { createWecomScanConfig, updateWecomScanConfig } from "../../api/admin";
import { ApiError } from "../../api/http";
import { useFormState } from "../../hooks/useFormState";
import type {
  WecomOwnerOptionDTO,
  WecomProjectOptionDTO,
  WecomScanConfigDTO,
} from "../../types/wecom";

interface WecomScanConfigFormProps {
  open: boolean;
  editingConfig: WecomScanConfigDTO | null;
  projectOptions: WecomProjectOptionDTO[];
  ownerOptions: WecomOwnerOptionDTO[];
  optionsError: boolean;
  onForbidden: () => void;
  onClose: () => void;
  onSaved: (config: WecomScanConfigDTO, note: string) => void;
}

const INITIAL = {
  name: "",
  projectId: "",
  ownerId: "",
  enabled: true,
};

function saveFailureMessage(error: unknown) {
  if (!(error instanceof ApiError)) return "配置未保存，请稍后重试。";
  if (error.deniedReason === "wecom_drive_permission_denied")
    return "企业微信应用未获得微盘权限，请管理员启用“协作-微盘-API”后重试。";
  if (error.deniedReason === "wecom_token_rejected" || error.deniedReason === "wecom_token_missing")
    return "企业微信应用凭证无效，请管理员检查应用凭证后重试。";
  if (error.deniedReason === "wecom_drive_network_unavailable")
    return "企业微信微盘暂时不可用，请稍后重试。";
  if (error.deniedReason === "wecom_space_manager_limit")
    return "项目经理人数超过企业微信空间管理员上限，请调整后重试。";
  return "配置未保存，请检查项目和业务归属人后重试。";
}

export default function WecomScanConfigForm({
  open,
  editingConfig,
  projectOptions,
  ownerOptions,
  optionsError,
  onForbidden,
  onClose,
  onSaved,
}: WecomScanConfigFormProps) {
  const { values, set, setMany, reset } = useFormState(INITIAL);
  const [saveBusy, setSaveBusy] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setSaveError(null);
    if (editingConfig) {
      setMany({
        name: editingConfig.name ?? "",
        projectId: editingConfig.related_project_id ?? "",
        ownerId: editingConfig.created_by,
        enabled: editingConfig.enabled,
      });
    } else {
      reset();
    }
  }, [open, editingConfig, reset, setMany]);

  const ownerCandidates = useMemo(
    () =>
      values.projectId
        ? ownerOptions.filter((owner) => owner.project_ids.includes(values.projectId))
        : [],
    [ownerOptions, values.projectId],
  );
  const selectedProject = projectOptions.find((project) => project.id === values.projectId);

  const handleSave = async () => {
    setSaveError(null);
    if (optionsError) {
      setSaveError("项目与业务归属选项加载失败，请刷新页面后再保存。");
      return;
    }
    if (!values.name.trim()) {
      setSaveError("请填写配置名称");
      return;
    }
    if (!values.projectId) {
      setSaveError("请选择目标项目");
      return;
    }
    if (!values.ownerId) {
      setSaveError("请选择待确认任务的业务归属人");
      return;
    }
    setSaveBusy(true);
    try {
      const saved = editingConfig
        ? await updateWecomScanConfig(editingConfig.id, {
            name: values.name.trim(),
            task_owner_user_id: values.ownerId,
            enabled: values.enabled,
          })
        : await createWecomScanConfig({
            name: values.name.trim(),
            target_project_id: values.projectId,
            task_owner_user_id: values.ownerId,
            enabled: values.enabled,
          });
      onSaved(saved, editingConfig ? "配置已更新。" : "项目扫描空间与配置已就绪。");
      onClose();
    } catch (error) {
      if (error instanceof ApiError && error.status === 403) onForbidden();
      setSaveError(saveFailureMessage(error));
    } finally {
      setSaveBusy(false);
    }
  };

  if (!open) return null;

  return (
    <section className="ws-section">
      <div className="ws87-form-panel">
        <div className="ws87-form-head">
          <span>{editingConfig ? "编辑扫描配置" : "新增项目扫描配置"}</span>
          <button className="btn-small" onClick={onClose} disabled={saveBusy}>
            关闭
          </button>
        </div>
        <div className="ws-form-grid">
          <label className="ws-form-field" htmlFor="ws-config-name">
            <span className="ws-form-label">配置名称</span>
            <input
              id="ws-config-name"
              className="ws-form-input"
              value={values.name}
              onChange={(event) => set("name", event.target.value)}
              placeholder="如：Alpha 项目资料扫描"
              maxLength={200}
            />
          </label>
          <label className="ws-form-field" htmlFor="ws-config-project">
            <span className="ws-form-label">目标项目</span>
            {editingConfig ? (
              <span className="ws-form-hint">
                {editingConfig.related_project_name ?? "当前项目"}（创建后不可更改）
              </span>
            ) : projectOptions.length > 0 ? (
              <select
                id="ws-config-project"
                className="ws-form-input"
                value={values.projectId}
                onChange={(event) => setMany({ projectId: event.target.value, ownerId: "" })}
              >
                <option value="">请选择项目…</option>
                {projectOptions.map((project) => (
                  <option key={project.id} value={project.id}>
                    {project.name}
                  </option>
                ))}
              </select>
            ) : (
              <span className="ws-form-hint">当前没有可管理的有效项目。</span>
            )}
            <span className="ws-form-hint">
              文件会递归扫描项目专属扫描空间的根目录；系统不会浏览或选择企业其他空间。
            </span>
            {selectedProject?.manager_access_status === "identity_link_required" && (
              <span className="ws-note-hint" role="status">
                项目经理尚未绑定企业微信身份。空间仍会创建，但需完成身份绑定后才能在企业微信中管理空间。
              </span>
            )}
          </label>
          <label className="ws-form-field" htmlFor="ws-config-owner">
            <span className="ws-form-label">待确认任务业务归属人</span>
            {values.projectId && ownerCandidates.length > 0 ? (
              <select
                id="ws-config-owner"
                className="ws-form-input"
                value={values.ownerId}
                onChange={(event) => set("ownerId", event.target.value)}
              >
                <option value="">请选择业务归属人…</option>
                {ownerCandidates.map((owner) => (
                  <option key={owner.user_id} value={owner.user_id}>
                    {owner.name}
                    {owner.role_label ? `（${owner.role_label}）` : ""}
                  </option>
                ))}
              </select>
            ) : (
              <span className="ws-form-hint">
                {values.projectId
                  ? "该项目暂无可选业务归属人。"
                  : "请先选择项目，再选择该项目的业务归属人。"}
              </span>
            )}
            <span className="ws-form-hint">
              配置操作人和任务业务归属人相互独立；扫描文件仍需由归属人确认后入库。
            </span>
          </label>
          <label className="ws-form-field ws-form-checkbox" htmlFor="ws-config-enabled">
            <input
              id="ws-config-enabled"
              type="checkbox"
              checked={values.enabled}
              onChange={(event) => set("enabled", event.target.checked)}
            />
            <span>创建后启用</span>
          </label>
        </div>
        {optionsError && (
          <div className="ws-note-hint" role="alert">
            项目与业务归属选项加载失败，请刷新页面后再配置。
          </div>
        )}
        {saveError && (
          <div className="ws-note-hint" role="alert">
            {saveError}
          </div>
        )}
        <div className="ws-form-actions">
          <button
            className="btn-small-primary"
            onClick={() => void handleSave()}
            disabled={saveBusy || optionsError}
          >
            {saveBusy ? "保存中…" : editingConfig ? "保存修改" : "创建配置"}
          </button>
          <button className="btn-small" onClick={onClose} disabled={saveBusy}>
            取消
          </button>
        </div>
      </div>
    </section>
  );
}
