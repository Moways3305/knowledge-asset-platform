import { useCallback, useEffect, useState } from "react";
import { Ban, CircleX, Clock3, LockKeyhole, RefreshCw, ShieldCheck } from "lucide-react";
import { fetchAuthSecurityOverview, unlockAuthLockout } from "../api/admin";
import { ApiError } from "../api/http";
import {
  OperationsSummary,
  PageHeader,
  PageToolbar,
  ProductPage,
} from "../components/ProductLayout";
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

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setData(await fetchAuthSecurityOverview({ windowMinutes, limit: 50 }));
    } catch (reason) {
      setData(null);
      setError(
        reason instanceof ApiError && reason.status === 403
          ? "当前身份没有登录安全运营权限。"
          : "登录安全状态暂时无法加载，请稍后重试。",
      );
    } finally {
      setLoading(false);
    }
  }, [windowMinutes]);

  useEffect(() => void load(), [load]);

  const onUnlock = useCallback(
    async (event: AuthSecurityEventDTO) => {
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
    [load],
  );

  const counts = data?.counts;
  return (
    <ProductPage className="secops-page auth-security-page admin-control-page">
      <PageHeader
        eyebrow="安全运营"
        title="登录安全"
        description="查看选定时间范围内的登录结果，并处理可解锁的账号状态。"
      />
      <div className="secops-console">
        <OperationsSummary
          label="登录安全摘要"
          titleIcon={<ShieldCheck size={15} aria-hidden="true" />}
          items={[
            {
              label: "失败",
              value: counts?.failed ?? 0,
              tone: "warning",
              icon: <CircleX size={14} />,
            },
            {
              label: "锁定",
              value: counts?.locked ?? 0,
              tone: "danger",
              icon: <LockKeyhole size={14} />,
            },
            {
              label: "访问限流",
              value: counts?.rate_limited ?? 0,
              tone: "danger",
              icon: <Ban size={14} />,
            },
          ]}
        />
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
            <div className="secops-workspace-heading">
              <span className="secops-workspace-heading-icon">
                <ShieldCheck size={16} />
              </span>
              <div>
                <strong>最近登录尝试</strong>
                <span>核查结果并处理可解锁账号</span>
              </div>
            </div>
            <PageToolbar
              className="secops-toolbar"
              start={
                <label className="secops-window">
                  <Clock3 size={14} aria-hidden="true" />
                  时间范围
                  <select
                    aria-label="时间范围"
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
            <div className="secops-table-wrap">
              <table className="secops-table">
                <thead>
                  <tr>
                    <th>时间</th>
                    <th>结果</th>
                    <th className="secops-col-secondary">原因</th>
                    <th>用户</th>
                    <th>账号状态</th>
                    <th>操作</th>
                  </tr>
                </thead>
                <tbody>
                  {(data?.recent_events ?? []).map((event) => (
                    <tr key={event.attempt_id}>
                      <td className="secops-time">{formatBeijingTime(event.created_at)}</td>
                      <td>
                        <span className={`secops-pill result-${event.result}`}>
                          {resultLabel[event.result] ?? "其他结果"}
                        </span>
                      </td>
                      <td className="secops-col-secondary">
                        {reasonLabel[event.reason_code ?? ""] ?? "安全校验未通过"}
                      </td>
                      <td className="secops-primary">{event.user_name ?? "未识别账号"}</td>
                      <td>{userStatusLabel[event.user_status ?? ""] ?? "状态未知"}</td>
                      <td>
                        {UNLOCKABLE.has(event.result) &&
                        (event.user_id || event.identifier_hash_prefix) ? (
                          <button
                            className="btn-small"
                            disabled={unlocking === event.attempt_id}
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
          </section>
        </main>
      </div>
    </ProductPage>
  );
}
