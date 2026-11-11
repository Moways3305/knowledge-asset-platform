import type { UserSessions } from "../../api/admin";
import { fetchAuthMe } from "../../api/auth";
import { useState } from "react";
import {
  fetchOperationUserOptions,
  reconcileWecomIdentity,
  revokeUserSessions,
} from "../../api/admin";
import { fetchUserSessions } from "../../api/admin";
import type { WecomReconcileResponseDTO } from "../../types/wecomIdentity";
import { formatBeijingTime } from "../../utils/time";
import { OperationPanel, ReadResult, useOperation } from "./OperationPanel";

function AccountTool({ mode }: { mode: "sessions" | "identity" }) {
  const [userId, setUserId] = useState("");
  const [lookupId, setLookupId] = useState("");
  return (
    <ReadResult
      refreshLabel="刷新账号列表"
      load={async () => {
        const [owners, me] = await Promise.all([fetchOperationUserOptions(), fetchAuthMe()]);
        return {
          items: [
            { user_id: me.userId, name: me.name, role_label: "当前账号" },
            ...owners.items.filter((item) => item.user_id !== me.userId),
          ],
        };
      }}
    >
      {(data) => (
        <div className="operation-form">
          <label>
            选择账号
            <select value={userId} onChange={(event) => setUserId(event.target.value)}>
              <option value="">请选择账号</option>
              {userId && !data.items.some((item) => item.user_id === userId) && (
                <option value={userId}>指定账号 · {userId}</option>
              )}
              {data.items.map((item) => (
                <option key={item.user_id} value={item.user_id}>
                  {item.name} · {item.role_label || "业务用户"}
                </option>
              ))}
            </select>
          </label>
          <details>
            <summary>按用户 ID 查询其他账号</summary>
            <div className="operation-form">
              <label>
                用户 ID
                <input
                  value={lookupId}
                  onChange={(event) => setLookupId(event.target.value)}
                  placeholder="输入审计记录中的用户 ID"
                />
              </label>
              <button
                className="btn-small"
                disabled={
                  !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(
                    lookupId.trim(),
                  )
                }
                onClick={() => setUserId(lookupId.trim())}
              >
                查看此账号
              </button>
            </div>
          </details>
          {mode === "identity" && (
            <p>核对所选账号的企业微信身份。未绑定的账号会提示无法核对；预览不会修改账号或会话。</p>
          )}
          {userId &&
            (mode === "sessions" ? (
              <SessionDetails key={userId} userId={userId} />
            ) : (
              <IdentityDetails key={userId} userId={userId} />
            ))}
        </div>
      )}
    </ReadResult>
  );
}

function SessionDetails({ userId }: { userId: string }) {
  const [revision, setRevision] = useState(0);
  const [reason, setReason] = useState("");
  const [confirming, setConfirming] = useState(false);
  const operation = useOperation();
  return (
    <>
      <ReadResult refreshLabel="刷新会话" key={revision} load={() => fetchUserSessions(userId)}>
        {(data) => (
          <>
            <strong>{data.active_count} 个有效会话</strong>
            {data.sessions
              .filter((item) => item.active)
              .map((item) => (
                <SessionCard key={item.session_id} item={item} />
              ))}
            {data.active_count === 1 &&
              data.sessions.some((item) => item.active && item.is_current_actor_session) && (
                <p>当前只有本次会话，已自动保留。</p>
              )}
            {data.active_count >
              data.sessions.filter((item) => item.active && item.is_current_actor_session)
                .length && (
              <div className="operation-form">
                <label>
                  撤销原因
                  <textarea
                    rows={2}
                    value={reason}
                    disabled={operation.busy}
                    onChange={(event) => {
                      setReason(event.target.value);
                      setConfirming(false);
                    }}
                  />
                </label>
                <p>撤销此账号的有效会话，账号需重新登录。如果操作自己的账号，将保留本次会话。</p>
                {!confirming ? (
                  <button
                    className="btn-small"
                    disabled={!reason.trim() || operation.busy}
                    onClick={() => setConfirming(true)}
                  >
                    撤销会话…
                  </button>
                ) : (
                  <div className="operation-actions">
                    <button
                      className="btn-small"
                      disabled={operation.busy}
                      onClick={() =>
                        void operation.run(async () => {
                          const result = await revokeUserSessions(userId, {
                            reason: reason.trim(),
                            preserve_current_session: true,
                          });
                          setConfirming(false);
                          setRevision((n) => n + 1);
                          return `已撤销 ${result.revoked_count} 个会话${result.preserved_current_session ? "，已保留当前会话" : ""}。`;
                        })
                      }
                    >
                      {operation.busy ? "撤销中…" : "确认撤销"}
                    </button>
                    <button
                      className="btn-small"
                      disabled={operation.busy}
                      onClick={() => setConfirming(false)}
                    >
                      取消
                    </button>
                  </div>
                )}
              </div>
            )}
            {data.sessions.some((item) => !item.active) && (
              <details>
                <summary>
                  历史失效会话（{data.sessions.filter((item) => !item.active).length}）
                </summary>
                <div className="operation-content">
                  {data.sessions
                    .filter((item) => !item.active)
                    .map((item) => (
                      <SessionCard key={item.session_id} item={item} />
                    ))}
                </div>
              </details>
            )}
          </>
        )}
      </ReadResult>
      {operation.feedback}
    </>
  );
}

function IdentityDetails({ userId }: { userId: string }) {
  const [preview, setPreview] = useState<WecomReconcileResponseDTO | null>(null);
  const operation = useOperation();
  return (
    <div className="operation-form">
      <button
        className="btn-small"
        disabled={operation.busy}
        onClick={() =>
          void operation.run(async () => {
            setPreview(null);
            const result = await reconcileWecomIdentity({ user_id: userId, dry_run: true });
            setPreview(result);
            return "预览完成，尚未修改账号。";
          })
        }
      >
        {operation.busy ? "处理中…" : "预览企微身份核对"}
      </button>
      {preview?.items.map((item) => (
        <article className="operation-card" key={item.user_id}>
          <strong>{item.user_name}</strong>
          <p>
            当前：{item.previous_status} → 核对结果：{item.new_status}
          </p>
          <p>企微状态：{item.wecom_status}</p>
          {item.error_code && <p role="alert">{item.error_code}</p>}
        </article>
      ))}
      {preview && preview.deactivated > 0 && preview.failed === 0 && (
        <>
          <p>确认后将按企业微信的最新状态停用此账号，并撤销有效会话。执行时会再次核对。</p>
          <button
            className="btn-small"
            disabled={operation.busy}
            onClick={() =>
              void operation.run(async () => {
                setPreview(null);
                const result = await reconcileWecomIdentity({ user_id: userId, dry_run: false });
                return `核对 ${result.checked} 个账号，停用 ${result.deactivated} 个，原已停用 ${result.already_inactive} 个，失败 ${result.failed} 个。`;
              })
            }
          >
            确认核对并应用
          </button>
        </>
      )}
      {operation.feedback}
    </div>
  );
}

export function SessionTools() {
  return (
    <div className="operation-actions">
      <OperationPanel label="会话管理">
        <AccountTool mode="sessions" />
      </OperationPanel>
      <OperationPanel label="企微身份核对">
        <AccountTool mode="identity" />
      </OperationPanel>
    </div>
  );
}

function SessionCard({ item }: { item: UserSessions["sessions"][number] }) {
  return (
    <article className="operation-card">
      <strong>
        {item.active ? "有效" : "已失效"}
        {item.is_current_actor_session ? " · 当前会话" : ""}
      </strong>
      <small>
        登录方式：
        {(
          { password: "密码登录", wecom: "企业微信", wecom_oauth: "企业微信" } as Record<
            string,
            string
          >
        )[item.login_method] ?? "其他登录方式"}
      </small>
      <p>登录时间：{formatBeijingTime(item.created_at)}</p>
      <p>最近活动：{formatBeijingTime(item.last_seen_at)}</p>
      <p>过期时间：{formatBeijingTime(item.expires_at)}</p>
    </article>
  );
}
