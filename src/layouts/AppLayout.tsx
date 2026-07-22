import { Suspense, useState } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router-dom";
import {
  LayoutDashboard,
  LibraryBig,
  UserRound,
  FileCheck2,
  ShieldCheck,
  KeyRound,
  FolderKanban,
  SlidersHorizontal,
  Inbox,
  ScanLine,
  Cpu,
  ScrollText,
  ShieldAlert,
  BellRing,
  KeySquare,
  Users,
  LifeBuoy,
  LogOut,
  PanelLeftClose,
  PanelLeftOpen,
  type LucideIcon,
} from "lucide-react";
import IdentityMenu from "../components/IdentityMenu";
import ErrorBoundary from "../components/ErrorBoundary";
import LoadingError from "../components/LoadingError";
import { AuthProvider, useAuth } from "../auth/AuthContext";
import { logout } from "../api/auth";
import { can, type Capability, type Capabilities } from "../auth/permissions";
import "./AppLayout.css";
import "../styles/workbench.css";
import "../styles/workbench-home-admin.css";
import "../styles/security-operations.css";
import "../styles/people-permissions-governance.css";
import "../styles/help-global-experience.css";

// 每个导航项带一个能力谓词 `cap`，与页面级守卫（RouteGuard）共用 `can` 判定，
// 保证「看得到的入口 = 进得去的页面」。无权入口直接不渲染，而非渲染后再报错。
type NavItem = { to: string; label: string; icon: LucideIcon; end?: boolean; cap: Capability };
type NavGroup = { label: string; items: NavItem[] };

const homeItem: NavItem = {
  to: "/",
  label: "今日工作台",
  icon: LayoutDashboard,
  end: true,
  cap: can.viewHome,
};

const navGroups: NavGroup[] = [
  {
    label: "业务功能",
    items: [
      {
        to: "/knowledge",
        label: "知识资产库",
        icon: LibraryBig,
        end: true,
        cap: can.viewKnowledge,
      },
      { to: "/my/knowledge", label: "个人知识", icon: UserRound, cap: can.viewMyKnowledge },
      { to: "/upload", label: "资产化确认", icon: FileCheck2, cap: can.viewUpload },
      { to: "/review", label: "升级审核", icon: ShieldCheck, cap: can.viewReview },
      { to: "/original-access", label: "原文访问", icon: KeyRound, cap: can.viewOriginalAccess },
      {
        to: "/project/:projectId",
        label: "项目空间",
        icon: FolderKanban,
        end: true,
        cap: can.viewProject,
      },
      {
        to: "/project/:projectId/knowledge",
        label: "项目知识库",
        icon: LibraryBig,
        cap: can.viewProject,
      },
      {
        to: "/project/:projectId/settings",
        label: "项目设置",
        icon: SlidersHorizontal,
        cap: can.viewProject,
      },
    ],
  },
  {
    label: "管理后台",
    items: [
      { to: "/admin/ingest", label: "入库管理", icon: Inbox, cap: can.viewIngestAdmin },
      { to: "/admin/wecom-scan", label: "微盘扫描", icon: ScanLine, cap: can.viewWecomScan },
      { to: "/admin/weknora-models", label: "模型配置", icon: Cpu, cap: can.viewModels },
      { to: "/admin/audit", label: "审计日志", icon: ScrollText, cap: can.viewAudit },
      {
        to: "/admin/auth-security",
        label: "登录风控",
        icon: ShieldAlert,
        cap: can.viewAuthSecurity,
      },
      { to: "/admin/alert-settings", label: "告警设置", icon: BellRing, cap: can.viewAlerts },
      { to: "/admin/permissions", label: "权限规则", icon: KeySquare, cap: can.viewPermissions },
      { to: "/admin/people", label: "人员权限", icon: Users, cap: can.viewPeople },
      {
        to: "/admin/company-kb",
        label: "公司知识库",
        icon: LibraryBig,
        cap: can.viewCompanyKnowledge,
      },
    ],
  },
];

const moduleTitles: Array<[prefix: string, title: string]> = [
  ["/project/", "项目空间"],
  ["/knowledge", "知识资产库"],
  ["/my/knowledge", "个人知识"],
  ["/upload", "资产化确认"],
  ["/review", "升级审核"],
  ["/original-access", "原文访问"],
  ["/admin/ingest", "入库管理"],
  ["/admin/wecom-scan", "微盘扫描"],
  ["/admin/weknora-models", "模型配置"],
  ["/admin/audit", "审计日志"],
  ["/admin/auth-security", "登录风控"],
  ["/admin/alert-settings", "告警设置"],
  ["/admin/permissions", "权限规则"],
  ["/admin/people", "人员权限"],
  ["/admin/company-kb", "公司知识库"],
  ["/help", "帮助"],
  ["/", "今日工作台"],
];

function currentModuleTitle(pathname: string): string {
  if (/^\/project\/[^/]+\/settings(?:\/|$)/.test(pathname)) return "项目设置";
  if (/^\/project\/[^/]+\/knowledge(?:\/|$)/.test(pathname)) return "项目知识库";
  return (
    moduleTitles.find(([prefix]) =>
      prefix === "/" ? pathname === "/" : pathname.startsWith(prefix),
    )?.[1] ?? "知识资产工作台"
  );
}

function RailLink({ item, collapsed }: { item: NavItem; collapsed: boolean }) {
  const Icon = item.icon;
  return (
    <li>
      <NavLink
        to={item.to}
        end={item.end}
        className={({ isActive }) => (isActive ? "active" : "")}
        aria-label={item.label}
        title={collapsed ? item.label : undefined}
      >
        <Icon size={18} className="rail-icon" strokeWidth={1.8} aria-hidden="true" />
        <span className="rail-label">{item.label}</span>
      </NavLink>
    </li>
  );
}

function RailNav({
  capabilities,
  projectId,
  collapsed,
}: {
  capabilities: Capabilities;
  projectId?: string;
  collapsed: boolean;
}) {
  // 按能力过滤：隐藏当前身份无意义的入口，并丢弃过滤后变空的分组（不留空标题）。
  const groups = navGroups
    .map((group) => ({
      ...group,
      items: group.items
        .filter((item) => item.cap(capabilities) && (!item.to.includes(":projectId") || projectId))
        .map((item) => ({
          ...item,
          to: projectId ? item.to.replace(":projectId", projectId) : item.to,
        })),
    }))
    .filter((group) => group.items.length > 0);
  return (
    <nav className="rail-nav" id="primary-navigation" aria-label="主导航">
      {homeItem.cap(capabilities) && (
        <div className="rail-group rail-group-lead">
          <ul>
            <RailLink item={homeItem} collapsed={collapsed} />
          </ul>
        </div>
      )}
      {groups.map((group) => (
        <div key={group.label} className="rail-group">
          <div className="rail-group-label">{group.label}</div>
          <ul>
            {group.items.map((item) => (
              <RailLink key={item.to} item={item} collapsed={collapsed} />
            ))}
          </ul>
        </div>
      ))}
    </nav>
  );
}

function AppShell() {
  const { authMe, capabilities, reload } = useAuth();
  const location = useLocation();
  const firstProjectId = authMe?.projects[0]?.projectId;
  const [railCollapsed, setRailCollapsed] = useState(false);
  const [logoutBusy, setLogoutBusy] = useState(false);
  const [logoutError, setLogoutError] = useState<string | null>(null);

  const handleLogout = async () => {
    setLogoutBusy(true);
    setLogoutError(null);
    try {
      await logout();
      await reload();
    } catch {
      setLogoutError("退出失败，请重试");
    } finally {
      setLogoutBusy(false);
    }
  };
  return (
    <div className={`app-layout ${railCollapsed ? "is-rail-collapsed" : ""}`}>
      <aside className="rail" aria-label="产品导航">
        <div className="rail-brand">
          <div className="rail-brand-row">
            <span className="rail-mark" aria-label="KAP">
              KAP
            </span>
            <button
              type="button"
              className="rail-collapse"
              onClick={() => setRailCollapsed((value) => !value)}
              aria-label={railCollapsed ? "展开主导航" : "折叠主导航"}
              aria-expanded={!railCollapsed}
              aria-controls="primary-navigation"
              title={railCollapsed ? "展开主导航" : "折叠主导航"}
            >
              {railCollapsed ? (
                <PanelLeftOpen size={18} aria-hidden="true" />
              ) : (
                <PanelLeftClose size={18} aria-hidden="true" />
              )}
            </button>
          </div>
          <span className="rail-sub">博维知识资产平台</span>
        </div>
        <RailNav capabilities={capabilities} projectId={firstProjectId} collapsed={railCollapsed} />
        <div className="rail-foot">
          {can.viewHelp(capabilities) && (
            <Link
              to="/help"
              className="rail-foot-link"
              aria-label="帮助"
              title={railCollapsed ? "帮助" : undefined}
            >
              <LifeBuoy size={18} aria-hidden="true" />
              <span className="rail-foot-label">帮助</span>
            </Link>
          )}
          {authMe && (
            <button
              type="button"
              className="rail-foot-link rail-foot-action"
              aria-label="退出登录"
              title={railCollapsed ? "退出登录" : undefined}
              disabled={logoutBusy}
              onClick={() => void handleLogout()}
            >
              <LogOut size={18} aria-hidden="true" />
              <span className="rail-foot-label">{logoutBusy ? "退出中…" : "退出登录"}</span>
            </button>
          )}
          {logoutError && (
            <span className="rail-foot-error" role="alert">
              {logoutError}
            </span>
          )}
          <div className="rail-identity">
            <IdentityMenu />
          </div>
        </div>
      </aside>

      <div className="app-main">
        <header className="deck">
          <div className="deck-context">
            <span className="deck-eyebrow">博维知识资产平台</span>
            <strong className="deck-title">{currentModuleTitle(location.pathname)}</strong>
          </div>
        </header>
        <main className="app-content">
          {/* 内容区兜底：页面 chunk 加载时显示 loading；某个页面渲染崩溃时只在此处显示
              错误卡片，左侧导航与顶栏不受影响（外层 App 还有一道全局 ErrorBoundary）。 */}
          <ErrorBoundary>
            <Suspense fallback={<LoadingError loading />}>
              <Outlet />
            </Suspense>
          </ErrorBoundary>
        </main>
      </div>
    </div>
  );
}

export default function AppLayout() {
  // AuthProvider 包裹整个外壳：导航过滤、身份菜单、页面守卫共享同一份 /auth/me。
  return (
    <AuthProvider>
      <AppShell />
    </AuthProvider>
  );
}
