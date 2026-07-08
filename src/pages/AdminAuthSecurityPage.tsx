import { useCallback, useEffect, useState } from "react";
import { RefreshCw, Unlock } from "lucide-react";
import { ApiError } from "../api/http";
import { fetchAuthSecurityOverview, unlockAuthLockout } from "../api/admin";
import type { AuthSecurityEventDTO, AuthSecurityOverviewDTO } from "../types/authSecurity";
import { formatBeijingTime } from "../utils/time";

// 登录风控运维。仅 admin 可见；展示安全聚合 + 最近事件 + 手动解锁入口。
// 全部为不可逆 hash 前缀 / 安全用户元数据；不展示 raw email / raw IP / 完整 hash / token。
const resultLabel: Record<string, string> = {
  failed: "失败",
  locked: "已锁定",
  rate_limited: "IP 限流",
  success: "成功",
  unlocked: "已解锁",
};
const reasonLabel: Record<string, string> = {
  invalid_credentials: "凭证错误",
  identifier_locked: "账号短时锁定",
  ip_rate_limited: "IP 限流",
  manual_unlock: "人工解锁",
  success: "成功",
};

// 可唯一定位、可解锁的事件（账号短时锁定 / 失败累积）。
const UNLOCKABLE = new Set(["locked", "failed", "rate_limited"]);

type Sev = "danger" | "warning" | "success" | "info";

export default function AdminAuthSecurityPage() {
  const [data, setData] = useState<AuthSecurityOverviewDTO | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [windowMinutes, setWindowMinutes] = useState(60);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setData(await fetchAuthSecurityOverview({ windowMinutes, limit: 50 }));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "加载登录风控数据失败");
    } finally {
      setLoading(false);
    }
  }, [windowMinutes]);

  useEffect(() => {
    void load();
  }, [load]);

  const onUnlock = useCallback(
    async (ev: AuthSecurityEventDTO) => {
      setNotice(null);
      setError(null);
      try {
        const body = ev.user_id
          ? { user_id: ev.user_id }
          : { identifier_hash_prefix: ev.identifier_hash_prefix ?? "" };
        const res = await unlockAuthLockout(body);
        setNotice(res.unlocked ? "已解除该账号的短时锁定。" : "未发生解锁。");
        await load();
      } catch (e) {
        setError(e instanceof ApiError ? e.message : "解锁失败，请稍后重试");
      }
    },
    [load],
  );

  const c = data?.counts;
  const risks: { label: string; value: number; sev: Sev }[] = c
    ? [
        { label: "失败", value: c.failed, sev: "warning" },
        { label: "锁定", value: c.locked, sev: "danger" },
        { label: "IP 限流", value: c.rate_limited, sev: "danger" },
        { label: "成功", value: c.success, sev: "success" },
        { label: "人工解锁", value: c.unlocked, sev: "info" },
        { label: "独立账号", value: c.unique_identifier_count, sev: "info" },
        { label: "独立 IP", value: c.unique_ip_count, sev: "info" },
      ]
    : [];

  return (
    <div className="cockpit">
      <div className="kb-masthead">
        <div>
          <div className="kb-eyebrow">Auth Security · 登录风控</div>
          <h2 className="kb-title">登录风控运营台</h2>
          <p className="kb-lead">查看近期登录风险和异常账号状态。</p>
        </div>
      </div>

      <div className="cockpit-bar">
        <label>
          时间窗口（分钟）
          <input
            type="number"
            min={1}
            max={10080}
            value={windowMinutes}
            onChange={(e) => setWindowMinutes(Math.max(1, Number(e.target.value) || 60))}
          />
        </label>
        <span className="cockpit-bar-spacer" />
        <button className="btn-small" onClick={() => void load()} disabled={loading}>
          <RefreshCw size={13} /> {loading ? "刷新中…" : "刷新"}
        </button>
      </div>

      {error && <div className="adminx-banner is-error">{error}</div>}
      {notice && <div className="adminx-banner is-ok">{notice}</div>}

      {risks.length > 0 && (
        <div className="cockpit-risks">
          {risks.map((r) => (
            <div key={r.label} className={`cockpit-risk sev-${r.sev}`}>
              <div className="cockpit-risk-value">{r.value}</div>
              <div className="cockpit-risk-label">{r.label}</div>
            </div>
          ))}
        </div>
      )}

      <div className="cockpit-events">
        <div className="cockpit-events-head">最近登录尝试</div>
        {(data?.recent_events ?? []).map((ev) => (
          <div key={ev.attempt_id} className="cockpit-event">
            <span className="cockpit-event-time">{formatBeijingTime(ev.created_at)}</span>
            <span className={`authres authres-${ev.result}`}>
              {resultLabel[ev.result] ?? ev.result}
            </span>
            <span className="cockpit-event-user">
              {ev.user_name ? `${ev.user_name}（${ev.user_status ?? ""}）` : "未知账号"}
              <span className="cockpit-event-reason">
                {" "}
                · {ev.reason_code ? (reasonLabel[ev.reason_code] ?? ev.reason_code) : "—"}
              </span>
            </span>
            <span className="cockpit-event-hash" title="账号标识前缀（不可逆）">
              {ev.identifier_hash_prefix ?? "—"}
            </span>
            <span className="cockpit-event-hash" title="IP 前缀（不可逆）">
              {ev.ip_hash_prefix ?? "—"}
            </span>
            <span>
              {UNLOCKABLE.has(ev.result) && (ev.user_id || ev.identifier_hash_prefix) ? (
                <button className="cockpit-unlock" onClick={() => void onUnlock(ev)}>
                  <Unlock size={12} /> 解锁
                </button>
              ) : null}
            </span>
          </div>
        ))}
        {data && data.recent_events.length === 0 && (
          <div className="cockpit-empty">该时间窗口内暂无登录尝试。</div>
        )}
        {!data && loading && <div className="cockpit-empty">加载中…</div>}
      </div>
    </div>
  );
}
