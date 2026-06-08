import { useCallback, useEffect, useState } from "react";
import { ApiError, fetchAuthSecurityOverview, unlockAuthLockout } from "../api/client";
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
    [load]
  );

  const c = data?.counts;

  return (
    <div className="page">
      <div className="page-header">
        <h2>登录风控</h2>
        <p className="page-sub">
          近 {data?.window_minutes ?? windowMinutes} 分钟登录尝试的安全聚合与手动解锁。仅显示不可逆
          标识前缀与安全用户元数据，不含邮箱 / IP / 密码 / 令牌。
        </p>
      </div>

      <div className="toolbar">
        <label>
          时间窗口（分钟）：
          <input
            type="number"
            min={1}
            max={10080}
            value={windowMinutes}
            onChange={(e) => setWindowMinutes(Math.max(1, Number(e.target.value) || 60))}
            style={{ width: 96, marginLeft: 6 }}
          />
        </label>
        <button onClick={() => void load()} disabled={loading} style={{ marginLeft: 12 }}>
          {loading ? "刷新中…" : "刷新"}
        </button>
      </div>

      {error && <div className="banner banner-error">{error}</div>}
      {notice && <div className="banner banner-ok">{notice}</div>}

      {c && (
        <div className="stat-cards">
          <div className="stat-card"><div className="stat-num">{c.failed}</div><div>失败</div></div>
          <div className="stat-card"><div className="stat-num">{c.locked}</div><div>锁定</div></div>
          <div className="stat-card"><div className="stat-num">{c.rate_limited}</div><div>IP 限流</div></div>
          <div className="stat-card"><div className="stat-num">{c.success}</div><div>成功</div></div>
          <div className="stat-card"><div className="stat-num">{c.unlocked}</div><div>人工解锁</div></div>
          <div className="stat-card"><div className="stat-num">{c.unique_identifier_count}</div><div>独立账号</div></div>
          <div className="stat-card"><div className="stat-num">{c.unique_ip_count}</div><div>独立 IP</div></div>
        </div>
      )}

      <table className="data-table">
        <thead>
          <tr>
            <th>时间</th>
            <th>结果</th>
            <th>原因</th>
            <th>用户</th>
            <th>账号标识前缀</th>
            <th>IP 前缀</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          {(data?.recent_events ?? []).map((ev) => (
            <tr key={ev.attempt_id}>
              <td>{formatBeijingTime(ev.created_at)}</td>
              <td>{resultLabel[ev.result] ?? ev.result}</td>
              <td>{ev.reason_code ? reasonLabel[ev.reason_code] ?? ev.reason_code : "—"}</td>
              <td>{ev.user_name ? `${ev.user_name}（${ev.user_status ?? ""}）` : "未知账号"}</td>
              <td><code>{ev.identifier_hash_prefix ?? "—"}</code></td>
              <td><code>{ev.ip_hash_prefix ?? "—"}</code></td>
              <td>
                {UNLOCKABLE.has(ev.result) && (ev.user_id || ev.identifier_hash_prefix) ? (
                  <button onClick={() => void onUnlock(ev)}>解锁</button>
                ) : (
                  "—"
                )}
              </td>
            </tr>
          ))}
          {data && data.recent_events.length === 0 && (
            <tr>
              <td colSpan={7}>该时间窗口内暂无登录尝试。</td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

