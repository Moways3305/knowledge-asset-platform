import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  ClipboardList,
  FileCheck2,
  ShieldCheck,
  KeyRound,
  Clock,
  AlertTriangle,
  RefreshCw,
  Gauge,
  Rocket,
  LibraryBig,
  UploadCloud,
  FolderKanban,
  UserRound,
  ScrollText,
  ShieldAlert,
  Users,
  Inbox,
  ChevronRight,
  Building2,
  Lightbulb,
} from "lucide-react";
import { fetchAuthMe, type AuthMeVM } from "../api/auth";
import { fetchKnowledgeOpsInsights, fetchOriginalAccessRequests } from "../api/knowledge";
import { fetchReviews } from "../api/review";
import { fetchPendingIngestTasks } from "../api/ingest";
import { fetchProjects } from "../api/project";
import type { KnowledgeOpsInsightsDTO } from "../types/insights";
import type { ProjectListItemDTO } from "../types/project";

const roleLabel: Record<string, string> = {
  boss: "Boss",
  consulting_director: "咨询总监",
  consultant: "顾问",
  admin: "管理员",
};
const projectRoleLabel: Record<string, string> = {
  project_manager: "项目经理",
  consultant: "顾问",
  coach: "辅导老师",
};

function greeting(): string {
  const h = new Date().getHours();
  if (h < 6) return "夜深了";
  if (h < 11) return "上午好";
  if (h < 13) return "中午好";
  if (h < 18) return "下午好";
  return "晚上好";
}

function todayLabel(): string {
  try {
    return new Intl.DateTimeFormat("zh-CN", {
      timeZone: "Asia/Shanghai",
      year: "numeric",
      month: "long",
      day: "numeric",
      weekday: "long",
    }).format(new Date());
  } catch {
    return "";
  }
}

// allSettled 友好包装：失败（含 403）返回 null，让对应待办自然隐藏，不造假。
async function attempt<T>(p: Promise<T>): Promise<T | null> {
  try {
    return await p;
  } catch {
    return null;
  }
}

type Todo = {
  key: string;
  label: string;
  desc: string;
  count: number;
  to: string;
  severity: "default" | "warning" | "danger";
  icon: typeof FileCheck2;
};

export default function HomeDashboardPage() {
  const [me, setMe] = useState<AuthMeVM | null>(null);
  const [insights, setInsights] = useState<KnowledgeOpsInsightsDTO | null>(null);
  const [pendingIngest, setPendingIngest] = useState<number | null>(null);
  const [pendingReviews, setPendingReviews] = useState<number | null>(null);
  const [originalInbox, setOriginalInbox] = useState<number | null>(null);
  const [originalMine, setOriginalMine] = useState<number | null>(null);
  const [projects, setProjects] = useState<ProjectListItemDTO[] | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const meRes = await attempt(fetchAuthMe());
      if (cancelled) return;
      setMe(meRes);

      const [ins, ingest, reviews, inbox, mine, projs] = await Promise.all([
        attempt(fetchKnowledgeOpsInsights({ scope: "company" })),
        attempt(fetchPendingIngestTasks()),
        attempt(fetchReviews({})),
        attempt(fetchOriginalAccessRequests("inbox")),
        attempt(fetchOriginalAccessRequests("mine")),
        attempt(fetchProjects()),
      ]);
      if (cancelled) return;
      setInsights(ins);
      setPendingIngest(ingest ? ingest.length : null);
      setPendingReviews(
        reviews ? reviews.filter((r) => r.status.startsWith("pending")).length : null,
      );
      setOriginalInbox(inbox ? inbox.items.filter((r) => r.status === "pending").length : null);
      setOriginalMine(mine ? mine.items.filter((r) => r.status === "pending").length : null);
      setProjects(projs ? projs.items : null);
      setLoading(false);
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const roles = me?.companyRoles ?? [];
  const isGovernance = roles.includes("boss") || roles.includes("consulting_director");
  const isAdmin = roles.includes("admin");
  const idxFailed = insights?.indexing.index_failed ?? 0;
  const idxSkipped = (insights?.indexing.skipped ?? 0) + (insights?.indexing.not_indexed ?? 0);
  const needsUpdate = insights?.lifecycle.needs_update ?? 0;
  const archiveCandidates = insights?.lifecycle.archive_candidates ?? 0;
  const reuseCandidates = insights?.lifecycle.reuse_upgrade_candidates ?? 0;
  const pendingOriginal = insights?.access.pending_original_requests ?? 0;
  const overdueOriginal = insights?.access.overdue_original_requests ?? 0;

  // 待办：仅显示 count>0 的真实项；调用失败/无权的项自然不出现。
  const todos: Todo[] = [];
  const push = (t: Todo) => {
    if (t.count > 0) todos.push(t);
  };
  if (pendingIngest != null)
    push({
      key: "ingest",
      label: "待确认入库任务",
      desc: "微盘扫描产生、等待资产化确认",
      count: pendingIngest,
      to: "/upload",
      severity: "default",
      icon: FileCheck2,
    });
  if (pendingReviews != null)
    push({
      key: "review",
      label: "待我审核",
      desc: "升级 / 资产化确认审核",
      count: pendingReviews,
      to: "/review",
      severity: "default",
      icon: ShieldCheck,
    });
  if (originalInbox != null)
    push({
      key: "oa-inbox",
      label: "待处理原文访问申请",
      desc: "需我审批的原文授权",
      count: originalInbox,
      to: "/original-access",
      severity: "warning",
      icon: KeyRound,
    });
  if (originalMine != null)
    push({
      key: "oa-mine",
      label: "我发起的原文申请",
      desc: "处理中的原文访问申请",
      count: originalMine,
      to: "/original-access",
      severity: "default",
      icon: Clock,
    });
  push({
    key: "idx",
    label: "索引失败待处理",
    desc: "检索索引失败，可重试",
    count: idxFailed,
    to: isAdmin || isGovernance ? "/admin/ingest" : "/knowledge",
    severity: "danger",
    icon: AlertTriangle,
  });
  push({
    key: "overdue",
    label: "原文申请已超时",
    desc: "超过自动通过时限仍待处理",
    count: overdueOriginal,
    to: "/original-access",
    severity: "warning",
    icon: Clock,
  });
  push({
    key: "update",
    label: "资产待更新",
    desc: "标记为需更新的知识资产",
    count: needsUpdate,
    to: "/knowledge",
    severity: "warning",
    icon: RefreshCw,
  });

  // 今日状态指标（来自真实运营洞察，按角色后端已裁剪）。
  const stats = insights
    ? [
        {
          key: "failed",
          label: "索引失败",
          value: idxFailed,
          tone: idxFailed > 0 ? "is-danger" : "",
          to: isAdmin || isGovernance ? "/admin/ingest" : "/knowledge",
        },
        { key: "skipped", label: "未索引", value: idxSkipped, tone: "", to: "/knowledge" },
        {
          key: "pending-oa",
          label: "原文待处理",
          value: pendingOriginal,
          tone: pendingOriginal > 0 ? "is-warning" : "",
          to: "/original-access",
        },
        {
          key: "update",
          label: "待更新",
          value: needsUpdate,
          tone: needsUpdate > 0 ? "is-warning" : "",
          to: "/knowledge",
        },
        { key: "archive", label: "归档候选", value: archiveCandidates, tone: "", to: "/knowledge" },
        {
          key: "reuse",
          label: "复用升格候选",
          value: reuseCandidates,
          tone: reuseCandidates > 0 ? "is-success" : "",
          to: "/knowledge",
        },
      ]
    : [];

  const businessQuick = [
    { to: "/knowledge", label: "知识资产库", icon: LibraryBig },
    { to: "/upload", label: "上传资产化", icon: UploadCloud },
    { to: "/review", label: "升级审核", icon: ShieldCheck },
    { to: "/original-access", label: "原文访问", icon: KeyRound },
    { to: "/project/current/knowledge", label: "项目看板", icon: FolderKanban },
    { to: "/my/knowledge", label: "个人知识", icon: UserRound },
  ];
  const adminQuick = [
    { to: "/admin/ingest", label: "入库管理", icon: Inbox },
    { to: "/admin/audit", label: "审计日志", icon: ScrollText },
    { to: "/admin/auth-security", label: "登录风控", icon: ShieldAlert },
    { to: "/admin/people", label: "人员权限", icon: Users },
  ];

  return (
    <div className="home">
      <div className="home-masthead">
        <div>
          <div className="home-eyebrow">Today · 今日工作台</div>
          <h2 className="home-greeting">
            {greeting()}，<span className="accent">{me?.name ?? "同事"}</span>
          </h2>
          <p className="home-submeta">
            平台身份：{roles.map((r) => roleLabel[r] ?? r).join(" / ") || "—"}
            {me && !me.isBusinessUser && " · 系统管理身份（仅运营视图）"}
          </p>
        </div>
        <div className="home-date">{todayLabel()}</div>
      </div>

      <div className="home-grid">
        <div className="home-col">
          {/* 我的待办 */}
          <section className="home-section">
            <div className="home-section-head">
              <span className="home-section-title">
                <ClipboardList size={16} /> 我的待办
              </span>
              <span className="home-section-eyebrow">Action items</span>
            </div>
            {loading ? (
              <div className="kb-state">
                <div className="kb-state-icon">
                  <ClipboardList size={20} />
                </div>
                <div className="kb-state-title">加载中…</div>
              </div>
            ) : todos.length > 0 ? (
              <div className="home-todos">
                {todos.map((t) => {
                  const Icon = t.icon;
                  return (
                    <Link key={t.key} to={t.to} className={`home-todo sev-${t.severity}`}>
                      <span className="home-todo-icon">
                        <Icon size={18} />
                      </span>
                      <span className="home-todo-body">
                        <span className="home-todo-label">{t.label}</span>
                        <span className="home-todo-desc">{t.desc}</span>
                      </span>
                      <span className="home-todo-count">{t.count}</span>
                      <ChevronRight size={18} className="home-todo-go" />
                    </Link>
                  );
                })}
              </div>
            ) : (
              <div className="kb-state">
                <div className="kb-state-icon">
                  <ShieldCheck size={20} />
                </div>
                <div className="kb-state-title">今日暂无待办</div>
                <p className="kb-state-desc">
                  没有需要你处理的入库确认、审核或原文申请。可从右侧快捷入口进入日常工作。
                </p>
              </div>
            )}
          </section>

          {/* 今日状态 */}
          {insights && (
            <section className="home-section">
              <div className="home-section-head">
                <span className="home-section-title">
                  <Gauge size={16} /> 今日状态
                </span>
                <span className="home-section-eyebrow">
                  {insights.window_days} 天窗口{!insights.title_visible && " · 运营视图"}
                </span>
              </div>
              <div className="home-stats">
                {stats.map((s) => (
                  <Link key={s.key} to={s.to} className="home-stat">
                    <div className={`home-stat-value ${s.tone}`}>{s.value}</div>
                    <div className="home-stat-label">{s.label}</div>
                  </Link>
                ))}
              </div>
            </section>
          )}

          {/* 运营建议（平台记录推荐，非业务结论） */}
          {insights && insights.recommendations.length > 0 && (
            <section className="home-section">
              <div className="home-section-head">
                <span className="home-section-title">
                  <Lightbulb size={16} /> 运营建议
                </span>
              </div>
              <div className="home-panel">
                <ul className="intel-recos">
                  {insights.recommendations.map((r) => (
                    <li key={r.key} className={`intel-reco sev-${r.severity}`}>
                      {r.target ? <Link to={r.target}>{r.message}</Link> : <span>{r.message}</span>}
                    </li>
                  ))}
                </ul>
              </div>
            </section>
          )}
        </div>

        {/* 侧栏：快捷入口 + 范围 + 最近动态 */}
        <aside className="home-aside">
          <div className="home-panel">
            <h4 className="home-panel-title">
              <Rocket size={13} /> 快捷入口
            </h4>
            <div className="home-quick">
              {businessQuick.map((q) => {
                const Icon = q.icon;
                return (
                  <Link key={q.to} to={q.to} className="home-quick-tile">
                    <Icon size={18} strokeWidth={1.75} />
                    <span className="home-quick-label">{q.label}</span>
                  </Link>
                );
              })}
            </div>
            {(isAdmin || isGovernance) && (
              <>
                <h4 className="home-panel-title" style={{ marginTop: 16 }}>
                  <ShieldAlert size={13} /> 管理后台
                </h4>
                <div className="home-quick">
                  {adminQuick.map((q) => {
                    const Icon = q.icon;
                    return (
                      <Link key={q.to} to={q.to} className="home-quick-tile">
                        <Icon size={18} strokeWidth={1.75} />
                        <span className="home-quick-label">{q.label}</span>
                      </Link>
                    );
                  })}
                </div>
              </>
            )}
          </div>

          <div className="home-panel">
            <h4 className="home-panel-title">
              <Building2 size={13} /> 我的项目范围
            </h4>
            {projects && projects.length > 0 ? (
              projects.slice(0, 6).map((p) => (
                <Link key={p.id} to={`/project/${p.id}/knowledge`} className="home-scope-item">
                  <span className="home-scope-name">{p.name}</span>
                  <span className="home-scope-role">
                    {p.status === "active" ? "进行中" : p.status}
                  </span>
                </Link>
              ))
            ) : me && me.projects.length > 0 ? (
              me.projects.map((p) => (
                <div key={p.projectId} className="home-scope-item">
                  <span className="home-scope-name">{p.projectName}</span>
                  <span className="home-scope-role">
                    {projectRoleLabel[p.projectRole] ?? p.projectRole}
                  </span>
                </div>
              ))
            ) : (
              <p className="home-scope-empty">
                暂无项目身份。可发现的公司知识仍可在知识资产库浏览。
              </p>
            )}
          </div>

          {insights && insights.recent_items.length > 0 && (
            <div className="home-panel">
              <h4 className="home-panel-title">
                <Clock size={13} /> 最近运营动态
              </h4>
              {insights.recent_items.slice(0, 5).map((it) => (
                <div key={it.asset_id} className="home-recent-item">
                  {insights.title_visible && it.title ? (
                    <Link to={`/knowledge/${it.asset_id}`}>{it.title}</Link>
                  ) : (
                    <span className="home-scope-empty">（业务标题已隐藏）</span>
                  )}
                  {it.message && <span className="home-recent-msg">{it.message}</span>}
                </div>
              ))}
            </div>
          )}
        </aside>
      </div>
    </div>
  );
}
