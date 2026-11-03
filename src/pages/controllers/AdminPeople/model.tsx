import { useState } from "react";
import ConfirmDialog from "../../../components/ConfirmDialog";
import { formatBeijingTime } from "../../../utils/time";
export const companyRoleLabel: Record<string, string> = {
  admin: "管理员",
  boss: "总经理",
  consulting_director: "咨询总监",
  consultant: "顾问",
};

export const projectRoleLabel: Record<string, string> = {
  consultant: "顾问",
  project_manager: "项目经理",
  coach: "辅导老师",
};

export const statusLabel: Record<string, string> = {
  active: "正常",
  inactive: "已停用",
};

export const statusCls: Record<string, string> = {
  active: "pp-status-active",
  inactive: "pp-status-disabled",
};

export const COMPANY_ROLE_OPTIONS = ["admin", "boss", "consulting_director", "consultant"];

export const PROJECT_ROLE_OPTIONS = ["project_manager"];

export const USER_STATUS_OPTIONS = ["active", "inactive"];

export const fmtTime = (iso: string | null): string => formatBeijingTime(iso);

export function SetPasswordForm({ onSubmit }: { onSubmit: (password: string) => Promise<void> }) {
  const [pw, setPw] = useState("");
  const [busy, setBusy] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const submit = async () => {
    if (!pw || busy) return;
    setConfirmOpen(true);
  };
  const confirmSubmit = async () => {
    setConfirmOpen(false);
    if (!pw || busy) return;
    setBusy(true);
    try {
      await onSubmit(pw);
      setPw(""); // 保存后立即清空，不回显
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="people-inline-form">
      <input
        className="up-edit-input"
        type="password"
        aria-label="新密码（至少 8 位）"
        disabled={busy}
        placeholder="新密码（至少 8 位）"
        value={pw}
        onChange={(e) => setPw(e.target.value)}
        autoComplete="new-password"
      />
      <button
        type="button"
        className="btn-small btn-small-primary"
        disabled={busy || !pw}
        onClick={() => void submit()}
      >
        {busy ? "设置中…" : "设置 / 重置密码"}
      </button>
      <ConfirmDialog
        open={confirmOpen}
        title="确认设置或重置该人员的登录密码？"
        description="设置后该人员将使用新密码登录；请通过安全渠道告知本人。"
        confirmText="确认设置"
        busyText="设置中…"
        busy={busy}
        danger
        onConfirm={() => void confirmSubmit()}
        onCancel={() => setConfirmOpen(false)}
      />
    </div>
  );
}

export function AddMembershipForm({
  projects,
  onSubmit,
}: {
  projects: { id: string; name: string }[];
  onSubmit: (projectId: string, role: string) => void;
}) {
  const [projectIndex, setProjectIndex] = useState(0);
  const [role, setRole] = useState(PROJECT_ROLE_OPTIONS[0] ?? "project_manager");
  if (projects.length === 0) {
    return (
      <p className="pp-no-project" style={{ marginTop: 8 }}>
        暂无可选项目（项目列表来自当前已加载人员的成员关系）。
      </p>
    );
  }
  return (
    <div className="people-inline-form">
      <select
        className="up-edit-select"
        aria-label="目标项目"
        value={projectIndex}
        onChange={(e) => setProjectIndex(Number(e.target.value))}
      >
        {projects.map((p, index) => (
          <option key={p.id} value={index}>
            {p.name}
          </option>
        ))}
      </select>
      <select className="up-edit-select" value={role} onChange={(e) => setRole(e.target.value)}>
        {PROJECT_ROLE_OPTIONS.map((r) => (
          <option key={r} value={r}>
            {projectRoleLabel[r]}
          </option>
        ))}
      </select>
      <button
        type="button"
        className="btn-small btn-small-primary"
        onClick={() => projects[projectIndex] && onSubmit(projects[projectIndex].id, role)}
      >
        新增 / 更新成员关系
      </button>
    </div>
  );
}
