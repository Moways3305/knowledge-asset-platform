import { useEffect, useMemo, useState } from "react";
import { ApiError } from "../../api/http";
import { createWecomScanConfig, updateWecomScanConfig } from "../../api/admin";
import type {
  WecomOwnerOptionDTO,
  WecomProjectOptionDTO,
  WecomScanConfigDTO,
} from "../../types/wecom";
import { useFormState } from "../../hooks/useFormState";
import WecomDirectoryPicker from "./WecomDirectoryPicker";
import { scopeOptions } from "./labels";

// 创建 / 编辑扫描配置表单。自包含表单态（useFormState）与保存调用；
// editingConfig=null 表示新建。保存成功后回调 onSaved（携带提示文案）并关闭。
interface WecomScanConfigFormProps {
  open: boolean;
  editingConfig: WecomScanConfigDTO | null;
  projectOptions: WecomProjectOptionDTO[];
  ownerOptions: WecomOwnerOptionDTO[];
  onClose: () => void;
  onSaved: (note: string) => void;
}

const INITIAL = {
  name: "",
  dir: "",
  dirLabel: "",
  scope: "project",
  projectId: "",
  ownerId: "",
  enabled: true,
};

export default function WecomScanConfigForm({
  open,
  editingConfig,
  projectOptions,
  ownerOptions,
  onClose,
  onSaved,
}: WecomScanConfigFormProps) {
  const { values, set, setMany, reset } = useFormState(INITIAL);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [saveBusy, setSaveBusy] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  const describeError = (e: unknown, fallback: string) =>
    e instanceof ApiError ? `${e.message}（${e.deniedReason ?? e.status}）` : fallback;

  // 打开时按新建 / 编辑初始化字段。
  useEffect(() => {
    if (!open) return;
    setSaveError(null);
    setPickerOpen(false);
    if (editingConfig) {
      setMany({
        name: editingConfig.name ?? "",
        dir: editingConfig.directory_path,
        dirLabel: "",
        scope: editingConfig.scope_type,
        projectId: editingConfig.related_project_id ?? "",
        ownerId: editingConfig.created_by,
        enabled: editingConfig.enabled,
      });
    } else {
      reset();
    }
  }, [open, editingConfig, reset, setMany]);

  // 业务归属人候选按目标 scope 过滤（后端最终校验为准；前端仅提示合法候选）。
  const ownerCandidates = useMemo(() => {
    if (values.scope === "project") {
      return values.projectId
        ? ownerOptions.filter((o) => o.project_ids.includes(values.projectId))
        : [];
    }
    if (values.scope === "company") {
      return ownerOptions.filter((o) => o.is_governance);
    }
    return ownerOptions; // personal：任意业务用户
  }, [ownerOptions, values.scope, values.projectId]);

  const handleSave = async () => {
    setSaveError(null);
    if (!values.name.trim()) {
      setSaveError("请填写配置名称");
      return;
    }
    if (!values.dir.trim()) {
      setSaveError("请选择企业微信微盘目录");
      return;
    }
    if (values.scope === "project" && !values.projectId) {
      setSaveError("项目级配置必须选择目标项目");
      return;
    }
    if (!values.ownerId) {
      setSaveError("请选择待确认任务的业务归属人");
      return;
    }
    setSaveBusy(true);
    const base = {
      name: values.name.trim(),
      directory_path: values.dir.trim(),
      target_scope: values.scope,
      target_project_id: values.scope === "project" ? values.projectId : null,
      task_owner_user_id: values.ownerId,
    };
    try {
      if (editingConfig) {
        await updateWecomScanConfig(editingConfig.id, { ...base, enabled: values.enabled });
        onSaved("配置已更新");
      } else {
        await createWecomScanConfig({ ...base, enabled: values.enabled });
        onSaved("配置已创建");
      }
      onClose();
    } catch (e) {
      setSaveError(describeError(e, "保存配置失败（创建/编辑需 admin 权限）"));
    } finally {
      setSaveBusy(false);
    }
  };

  if (!open) return null;

  return (
    <section className="ws-section">
      <div className="ws-detail-panel">
        <div className="ws-detail-head">
          <span className="ws-detail-title">{editingConfig ? "编辑扫描配置" : "新增扫描配置"}</span>
          <button className="btn-small" onClick={onClose} disabled={saveBusy}>
            关闭
          </button>
        </div>
        <div className="ws-form-grid">
          <label className="ws-form-field">
            <span className="ws-form-label">配置名称</span>
            <input
              className="ws-form-input"
              value={values.name}
              onChange={(e) => set("name", e.target.value)}
              placeholder="如：Alpha 项目交付目录"
              maxLength={200}
            />
          </label>
          <div className="ws-form-field">
            <span className="ws-form-label">扫描目录</span>
            <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
              <button
                className="btn-small btn-small-primary"
                type="button"
                onClick={() => setPickerOpen((v) => !v)}
              >
                {pickerOpen ? "收起目录选择" : "选择微盘目录"}
              </button>
              <span className="ws-form-hint">
                {values.dir
                  ? values.dirLabel
                    ? `已选择：${values.dirLabel}`
                    : "已设置服务端目录配置"
                  : "从微盘空间/目录中选择"}
              </span>
            </div>
            {pickerOpen && (
              <WecomDirectoryPicker
                onSelect={(ref, label) => {
                  setMany({ dir: ref, dirLabel: label });
                  setPickerOpen(false);
                }}
              />
            )}
            <details className="ws-form-advanced" style={{ marginTop: 8 }}>
              <summary
                style={{ cursor: "pointer", fontSize: 12, color: "var(--color-text-muted, #888)" }}
              >
                高级：手动输入目录标识
              </summary>
              <input
                className="ws-form-input"
                style={{ marginTop: 6 }}
                value={values.dir}
                onChange={(e) => setMany({ dir: e.target.value, dirLabel: "" })}
                placeholder="spaceid:<id>;fatherid:<id>"
              />
              <span className="ws-form-hint">
                技术详情，格式 <code>spaceid:&lt;id&gt;;fatherid:&lt;id&gt;</code>；fatherid
                省略表示根目录。
              </span>
            </details>
          </div>
          <label className="ws-form-field">
            <span className="ws-form-label">目标知识库</span>
            <select
              className="ws-form-input"
              value={values.scope}
              onChange={(e) => {
                setMany({
                  scope: e.target.value,
                  ownerId: "",
                  ...(e.target.value !== "project" ? { projectId: "" } : {}),
                });
              }}
            >
              {scopeOptions.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          </label>
          {values.scope === "project" && (
            <label className="ws-form-field">
              <span className="ws-form-label">目标项目</span>
              {projectOptions.length > 0 ? (
                <select
                  className="ws-form-input"
                  value={values.projectId}
                  onChange={(e) => setMany({ projectId: e.target.value, ownerId: "" })}
                >
                  <option value="">请选择项目…</option>
                  {projectOptions.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name}
                    </option>
                  ))}
                </select>
              ) : (
                <span className="ws-form-hint">
                  暂无可选的 active 项目，请先创建项目后再配置项目级扫描。
                </span>
              )}
            </label>
          )}
          <label className="ws-form-field">
            <span className="ws-form-label">待确认任务业务归属人</span>
            {(values.scope !== "project" || values.projectId) && ownerCandidates.length > 0 ? (
              <select
                className="ws-form-input"
                value={values.ownerId}
                onChange={(e) => set("ownerId", e.target.value)}
              >
                <option value="">请选择业务归属人…</option>
                {ownerCandidates.map((o) => (
                  <option key={o.user_id} value={o.user_id}>
                    {o.name}
                    {o.role_label ? `（${o.role_label}）` : ""}
                  </option>
                ))}
              </select>
            ) : (
              <span className="ws-form-hint">
                {values.scope === "project" && !values.projectId
                  ? "请先选择目标项目，再选择该项目的业务归属人。"
                  : values.scope === "company"
                    ? "公司级配置需选择 Boss / 咨询总监作为业务归属人，当前无可选治理角色。"
                    : "暂无可选业务用户作为归属人。"}
              </span>
            )}
            <span className="ws-form-hint">
              扫描发现的文件会生成待确认入库任务，由该业务归属人进入资产化确认工作台处理（配置操作人仍是当前
              admin）。
            </span>
          </label>
          <label className="ws-form-field ws-form-checkbox">
            <input
              type="checkbox"
              checked={values.enabled}
              onChange={(e) => set("enabled", e.target.checked)}
            />
            <span>创建后启用</span>
          </label>
        </div>
        {saveError && (
          <div className="ws-note-hint" style={{ color: "var(--color-danger-fg, #b00)" }}>
            {saveError}
          </div>
        )}
        <div className="ws-form-actions">
          <button
            className="btn-small-primary"
            onClick={() => void handleSave()}
            disabled={saveBusy}
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
