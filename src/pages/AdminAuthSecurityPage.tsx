import { SessionTools } from "../components/operations/SessionTools";
import CollectionWorkspace from "../components/CollectionWorkspace";
import { useCallback, useEffect, useRef, useState } from "react";
import { Clock3, RefreshCw } from "lucide-react";
import { fetchAuthSecurityOverview, unlockAuthLockout } from "../api/admin";
import { ApiError } from "../api/http";
import { PageHeader, PageToolbar, ProductPage } from "../components/ProductLayout";
import type { AuthSecurityEventDTO, AuthSecurityOverviewDTO } from "../types/authSecurity";
import { formatBeijingTime } from "../utils/time";

const resultLabel: Record<string, string> = {
  failed: "失败",
  locked: "已锁定",
  rate_limited: "已限流",
  success: "成功",
  unlocked: "已解锁",
};
const reasonLabel: Record<string, string> = {
  invalid_credentials: "凭证校验失败",
  identifier_locked: "账号短时锁定",
  ip_rate_limited: "访问频率受限",
  manual_unlock: "人工解锁",
  success: "验证通过",
};
const userStatusLabel: Record<string, string> = {
  active: "正常",
  disabled: "已停用",
  locked: "已锁定",
  inactive: "未启用",
};
const UNLOCKABLE = new Set(["locked", "failed", "rate_limited"]);

export default function AdminAuthSecurityPage() {
  const [data, setData] = useState<AuthSecurityOverviewDTO | null>(null);
  const [windowMinutes, setWindowMinutes] = useState(60);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [unlocking, setUnlocking] = useState<string | null>(null);
  const listRequest = useRef(0);

  const load = useCallback(async () => {
    const request = ++listRequest.current;
    setLoading(true);
    setError(null);
    try {
      const result = await fetchAuthSecurityOverview({ windowMinutes, limit: 50 });
      if (request !== listRequest.current) return;
      setData(result);
    } catch (reason) {
      if (request !== listRequest.current) return;
      setData(null);
      setError(
        reason instanceof ApiError && reason.status === 403
          ? "当前身份没有登录安全运营权限。"
          : "登录安全状态暂时无法加载，请稍后重试。",
      );
    } finally {
      if (request === listRequest.current) setLoading(false);
    }
  }, [windowMinutes]);

  useEffect(() => {
    void load();
    return () => {
      listRequest.current += 1;
    };
  }, [load]);

  const onUnlock = useCallback(
    async (event: AuthSecurityEventDTO) => {
      if (unlocking || loading) return;
      if (!UNLOCKABLE.has(event.result) || (!event.user_id && !event.identifier_hash_prefix))
        return;
      setUnlocking(event.attempt_id);
      setError(null);
      setNotice(null);
      try {
        const response = await unlockAuthLockout(
          event.user_id
            ? { user_id: event.user_id }
            : { identifier_hash_prefix: event.identifier_hash_prefix ?? "" },
        );
        setNotice(response.unlocked ? "账号短时锁定已解除。" : "该账号当前无需解锁。");
        await load();
      } catch (reason) {
        setError(
          reason instanceof ApiError && reason.status === 403
            ? "当前身份不能执行解锁操作。"
            : "解锁失败，请稍后重试。",
        );
      } finally {
        setUnlocking(null);
      }
    },
    [load, unlocking, loading],
  );

  return (
    <ProductPage className="secops-page auth-security-page admin-control-page">
      <PageHeader
        title="登录安全"
        actions={<SessionTools />}
        description="核查最近登录尝试，处理符合条件的账号解锁。"
      />
      <div className="secops-console">
        <main className="secops-main-workspace">
          {error && (
            <div className="secops-banner is-error" role="alert">
              {error}
            </div>
          )}
          {notice && (
            <div className="secops-banner is-success" role="status">
              {notice}
            </div>
          )}
          <section className="secops-workspace" aria-label="最近登录尝试">
            <CollectionWorkspace
              filters={
                <PageToolbar
                  className="secops-toolbar"
                  start={
                    <label className="secops-window">
                      <Clock3 size={14} aria-hidden="true" />
                      时间范围（北京时间）
                      <select
                        aria-label="时间范围"
                        disabled={Boolean(unlocking)}
                        value={windowMinutes}
                        onChange={(event) => setWindowMinutes(Number(event.target.value))}
                      >
                        <option value={30}>最近 30 分钟</option>
                        <option value={60}>最近 1 小时</option>
                        <option value={360}>最近 6 小时</option>
                        <option value={1440}>最近 24 小时</option>
                        <option value={10080}>最近 7 天</option>
                      </select>
                    </label>
                  }
                  end={
                    <div className="secops-toolbar-actions">
                      <span className="secops-count">
                        最近登录尝试 {data?.recent_events.length ?? 0} 条
                      </span>
                      <button className="btn-small" onClick={() => void load()} disabled={loading}>
                        <RefreshCw size={13} aria-hidden="true" /> {loading ? "刷新中…" : "刷新"}
                      </button>
                    </div>
                  }
                />
              }
            >
              <p className="admin-list-context">
                显示所选时间范围内最近 50 条尝试。失败记录是历史结果，不代表账号当前仍被锁定。
              </p>
              <div className="secops-table-wrap">
                <table data-responsive-table className="secops-table">
                  <thead>
                    <tr>
                      <th>时间</th>
                      <th>结果</th>
                      <th>原因</th>
                      <th>用户</th>
                      <th>账号状态</th>
                      <th>操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    {[...(data?.recent_events ?? [])]
                      .sort(
                        (left, right) =>
                          Number(!UNLOCKABLE.has(left.result)) -
                          Number(!UNLOCKABLE.has(right.result)),
                      )
                      .map((event) => (
                        <tr
                          key={event.attempt_id}
                          className={UNLOCKABLE.has(event.result) ? "is-actionable" : ""}
                        >
                          <td data-label="时间" className="secops-time">
                            {formatBeijingTime(event.created_at)}
                          </td>
                          <td data-label="结果">
                            <span className={`secops-pill result-${event.result}`}>
                              {resultLabel[event.result] ?? "其他结果"}
                            </span>
                          </td>
                          <td data-label="原因">
                            {reasonLabel[event.reason_code ?? ""] ??
                              (event.result === "success"
                                ? "登录成功"
                                : event.result === "unlocked"
                                  ? "已解除锁定"
                                  : "未提供原因")}
                          </td>
                          <td data-label="用户" className="secops-primary">
                            {event.user_name ?? "未识别账号"}
                          </td>
                          <td data-label="账号状态">
                            {userStatusLabel[event.user_status ?? ""] ?? "状态未知"}
                          </td>
                          <td data-label="操作">
                            {UNLOCKABLE.has(event.result) &&
                            (event.user_id || event.identifier_hash_prefix) ? (
                              <button
                                className="btn-small"
                                disabled={Boolean(unlocking) || loading}
                                onClick={() => void onUnlock(event)}
                              >
                                {unlocking === event.attempt_id ? "解锁中…" : "解除锁定"}
                              </button>
                            ) : (
                              <span className="secops-muted">无需操作</span>
                            )}
                          </td>
                        </tr>
                      ))}
                    {!loading && data && data.recent_events.length === 0 && (
                      <tr>
                        <td colSpan={6} className="secops-empty">
                          该时间范围内暂无登录尝试
                        </td>
                      </tr>
                    )}
                    {loading && (
                      <tr>
                        <td colSpan={6} className="secops-empty">
                          正在加载登录安全状态…
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </CollectionWorkspace>
          </section>
        </main>
      </div>
    </ProductPage>
  );
}
