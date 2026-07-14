import { Suspense } from "react";
import { NavLink, Outlet } from "react-router-dom";
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
  type LucideIcon,
} from "lucide-react";
import IdentityMenu from "../components/IdentityMenu";
import ErrorBoundary from "../components/ErrorBoundary";
import LoadingError from "../components/LoadingError";
import { AuthProvider, useAuth } from "../auth/AuthContext";
import { can, type Capability, type Capabilities } from "../auth/permissions";
import logoUrl from "../assets/moways-logo.png";
import "./AppLayout.css";
import "../styles/workbench.css";
import "../styles/workbench-home-admin.css";

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
      { to: "/knowledge", label: "知识资产库", icon: LibraryBig, cap: can.viewKnowledge },
      { to: "/my/knowledge", label: "个人知识", icon: UserRound, cap: can.viewMyKnowledge },
      { to: "/upload", label: "资产化确认", icon: FileCheck2, cap: can.viewUpload },
      { to: "/review", label: "升级审核", icon: ShieldCheck, cap: can.viewReview },
      { to: "/original-access", label: "原文访问", icon: KeyRound, cap: can.viewOriginalAccess },
      {
        to: "/project/:projectId/knowledge",
        label: "项目看板",
        icon: FolderKanban,
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
    ],
  },
  {
    label: "帮助",
    items: [{ to: "/help", label: "使用说明", icon: LifeBuoy, cap: can.viewHelp }],
  },
];

function RailLink({ item }: { item: NavItem }) {
  const Icon = item.icon;
  return (
    <li>
      <NavLink to={item.to} end={item.end} className={({ isActive }) => (isActive ? "active" : "")}>
        <Icon size={16} className="rail-icon" strokeWidth={1.75} />
        <span className="rail-label">{item.label}</span>
      </NavLink>
    </li>
  );
}

function RailNav({ capabilities, projectId }: { capabilities: Capabilities; projectId?: string }) {
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
    <nav className="rail-nav">
      {homeItem.cap(capabilities) && (
        <div className="rail-group rail-group-lead">
          <ul>
            <RailLink item={homeItem} />
          </ul>
        </div>
      )}
      {groups.map((group) => (
        <div key={group.label} className="rail-group">
          <div className="rail-group-label">{group.label}</div>
          <ul>
            {group.items.map((item) => (
              <RailLink key={item.to} item={item} />
            ))}
          </ul>
        </div>
      ))}
    </nav>
  );
}

function AppShell() {
  const { authMe, capabilities } = useAuth();
  const firstProjectId = authMe?.projects[0]?.projectId;
  return (
    <div className="app-layout">
      <aside className="rail">
        <div className="rail-brand">
          <span className="rail-mark">Kivo</span>
          <span className="rail-sub">博维知识资产平台</span>
        </div>
        <RailNav capabilities={capabilities} projectId={firstProjectId} />
        <div className="rail-foot">
          <span className="rail-foot-line">知识资产与交付治理</span>
        </div>
      </aside>

      <div className="app-main">
        <header className="deck">
          <div className="deck-brand">
            {/* 真实公司品牌资产；产品名见左侧导航 */}
            <img className="deck-logo" src={logoUrl} alt="MOWAYS 博维咨询" />
          </div>
          <div className="deck-identity">
            <IdentityMenu />
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
