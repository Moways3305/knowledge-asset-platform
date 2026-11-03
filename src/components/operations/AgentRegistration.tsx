import { useState } from "react";
import { fetchWecomScanOwnerOptions, fetchWecomScanProjectOptions } from "../../api/admin";
import { registerAgent, type AgentRegistration as Registration } from "../../api/admin";
import { OperationPanel, ReadResult, useOperation } from "./OperationPanel";

function RegistrationForm({ onCreated }: { onCreated: () => void }) {
  const [draft, setDraft] = useState<Registration>({
    provider: "custom",
    agent_identifier: "",
    agent_name: "",
    capability: "qa",
    allowed_scope: "project",
    max_confidentiality_level: "L2",
    max_ai_access_level: "A2",
    enabled: false,
  });
  const [confirmation, setConfirmation] = useState(false);
  const [created, setCreated] = useState(false);
  const [token, setToken] = useState<string | null>(null);
  const [reveal, setReveal] = useState(false);
  const operation = useOperation();
  const valid = Boolean(
    draft.agent_name.trim() &&
    draft.agent_identifier.trim() &&
    (draft.provider !== "workbuddy" || draft.bound_user_id) &&
    (draft.allowed_scope !== "project" || draft.allowed_project_id),
  );
  const change = <K extends keyof Registration>(key: K, value: Registration[K]) =>
    setDraft((previous) => ({ ...previous, [key]: value }));
  if (created)
    return (
      <div className="operation-form">
        <p role="status">
          白名单已创建{draft.enabled ? "并启用" : "，当前未启用"}。可在列表中管理启用状态。
        </p>
        {token && (
          <>
            <p>接入凭证仅本次展示，关闭后无法再次查看。请保存到安全的凭证管理工具。</p>
            <label>
              接入凭证
              <input
                type={reveal ? "text" : "password"}
                readOnly
                value={token}
                autoComplete="off"
              />
            </label>
            <button className="btn-small" onClick={() => setReveal((value) => !value)}>
              {reveal ? "隐藏凭证" : "显示凭证"}
            </button>
          </>
        )}
      </div>
    );
  return (
    <form
      className="operation-form"
      onSubmit={(event) => {
        event.preventDefault();
        if (valid) setConfirmation(true);
      }}
    >
      <p>
        白名单限定助手的访问上限，实际访问仍受绑定用户、项目成员关系和资料权限约束。当前支持知识问答。
      </p>
      <fieldset disabled={operation.busy || confirmation} className="operation-form">
        <label>
          助手名称
          <input
            required
            maxLength={100}
            value={draft.agent_name}
            onChange={(event) => change("agent_name", event.target.value)}
          />
        </label>
        <label>
          接入标识
          <input
            required
            maxLength={200}
            value={draft.agent_identifier}
            onChange={(event) => change("agent_identifier", event.target.value)}
          />
        </label>
        <label>
          接入方式
          <select
            value={draft.provider}
            onChange={(event) => change("provider", event.target.value)}
          >
            <option value="custom">自定义助手</option>
            <option value="workbuddy">WorkBuddy</option>
          </select>
        </label>
        <ReadResult refreshLabel={false} load={() => fetchWecomScanOwnerOptions()}>
          {(data) => (
            <label>
              绑定业务用户
              <select
                required={draft.provider === "workbuddy"}
                value={draft.bound_user_id ?? ""}
                onChange={(event) => change("bound_user_id", event.target.value || undefined)}
              >
                <option value="">
                  {draft.provider === "workbuddy" ? "请选择业务用户" : "不绑定"}
                </option>
                {data.items.map((item) => (
                  <option key={item.user_id} value={item.user_id}>
                    {item.name}
                    {item.role_label ? ` · ${item.role_label}` : ""}
                  </option>
                ))}
              </select>
            </label>
          )}
        </ReadResult>
        <label>
          允许范围
          <select
            value={draft.allowed_scope ?? ""}
            onChange={(event) => change("allowed_scope", event.target.value || null)}
          >
            <option value="project">指定项目</option>
            <option value="company">公司库</option>
            <option value="personal">个人库</option>
            <option value="">全部授权范围</option>
          </select>
        </label>
        {draft.allowed_scope === "project" && (
          <ReadResult refreshLabel={false} load={fetchWecomScanProjectOptions}>
            {(data) => (
              <label>
                项目
                <select
                  required
                  value={draft.allowed_project_id ?? ""}
                  onChange={(event) => change("allowed_project_id", event.target.value)}
                >
                  <option value="">请选择项目</option>
                  {data.items.map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.name}
                    </option>
                  ))}
                </select>
              </label>
            )}
          </ReadResult>
        )}
        <label>
          最高密级
          <select
            value={draft.max_confidentiality_level}
            onChange={(event) => change("max_confidentiality_level", event.target.value)}
          >
            {["L1", "L2", "L3", "L4", "L5"].map((level) => (
              <option key={level}>{level}</option>
            ))}
          </select>
        </label>
        <label>
          最高 AI 使用等级
          <select
            value={draft.max_ai_access_level}
            onChange={(event) => change("max_ai_access_level", event.target.value)}
          >
            {["A1", "A2", "A3"].map((level) => (
              <option key={level}>{level}</option>
            ))}
          </select>
        </label>
        <label className="operation-check">
          <input
            type="checkbox"
            checked={draft.enabled}
            onChange={(event) => change("enabled", event.target.checked)}
          />
          创建后立即启用
        </label>
      </fieldset>
      {!confirmation ? (
        <button className="btn-small" type="submit" disabled={operation.busy || !valid}>
          核对并创建
        </button>
      ) : (
        <>
          <p>
            确认创建“{draft.agent_name}”，最高密级 {draft.max_confidentiality_level}，AI 等级{" "}
            {draft.max_ai_access_level}，{draft.enabled ? "立即启用" : "暂不启用"}。
          </p>
          <div className="operation-actions">
            <button
              className="btn-small"
              type="button"
              disabled={operation.busy}
              onClick={() =>
                void operation.run(async () => {
                  const result = await registerAgent({
                    ...draft,
                    agent_identifier: draft.agent_identifier.trim(),
                    agent_name: draft.agent_name.trim(),
                    allowed_project_id:
                      draft.allowed_scope === "project" ? draft.allowed_project_id : undefined,
                  });
                  setToken(result.token);
                  setCreated(true);
                  onCreated();
                  return "已创建白名单。";
                })
              }
            >
              {operation.busy ? "创建中…" : "确认创建"}
            </button>
            <button
              className="btn-small"
              type="button"
              disabled={operation.busy}
              onClick={() => setConfirmation(false)}
            >
              返回修改
            </button>
          </div>
        </>
      )}
      {operation.feedback}
    </form>
  );
}
export function AgentRegistrationButton({ onCreated }: { onCreated: () => void }) {
  return (
    <OperationPanel label="新增助手">
      <RegistrationForm onCreated={onCreated} />
    </OperationPanel>
  );
}
