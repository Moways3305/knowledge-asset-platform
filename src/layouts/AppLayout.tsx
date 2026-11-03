import { Suspense, useEffect, useState } from "react";
import { Link, Outlet, useLocation } from "react-router-dom";
import {
  LayoutDashboard,
  LibraryBig,
  ShieldCheck,
  FolderKanban,
  Settings2,
  LifeBuoy,
  Menu,
  PanelLeftClose,
  PanelLeftOpen,
  ChevronRight,
  ArrowLeft,
  UserRound,
} from "lucide-react";
import IdentityMenu from "../components/IdentityMenu";
import NotificationBell from "../components/NotificationBell";
import ReleaseNotesLink from "../components/ReleaseNotesLink";
import GlobalTaskStatus from "../components/GlobalTaskStatus";
import ErrorBoundary from "../components/ErrorBoundary";
import LoadingError from "../components/LoadingError";
import DetailDrawer from "../components/DetailDrawer";
import ModuleNavigation from "../components/ModuleNavigation";
import { ActionMenu } from "../components/ActionLayout";
import { AuthProvider, useAuth } from "../auth/AuthContext";
import LoginGate from "../auth/LoginGate";
import { can } from "../auth/permissions";
import { HistoryBackButton, SafeNavigationProvider } from "../routing/SafeNavigation";
import { WorkbenchProvider } from "../workbench/WorkbenchContext";
import {
  approvalEntries,
  knowledgeEntries,
  managementEntries,
  permittedEntries,
  workspaceForPath,
  workspaceLabels,
  pageTitle,
} from "../navigation/workspaces";
import "./AppLayout.css";
import "../styles/workbench.css";
import "../styles/workbench-home-admin.css";
import "../styles/security-operations.css";
import "../styles/people-permissions-governance.css";
import "../styles/help-global-experience.css";
import "../styles/experience-system.css";
import "../styles/admin-console.css";
import "../styles/refined-workspaces.css";
import "../styles/knowledge-workspaces.css";
import "../styles/workspace-rollout.css";
import "../styles/workspace-content.css";
import "../styles/workspace-shell.css";
import "../styles/product-workspaces.css";
import "../styles/admin-management.css";

const mobileLabels: Record<string, string> = {
  work: "工作",
  knowledge: "知识",
  project: "项目",
  approval: "审批",
};

function AppShell() {
  const { authMe, capabilities } = useAuth();
  const location = useLocation();
  const workspace = workspaceForPath(location.pathname);
  const projectPath = "/projects";
  const managers = permittedEntries(managementEntries, capabilities);
  const [railCollapsed, setRailCollapsed] = useState(false);
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const focusLayout =
    /^\/knowledge\/[^/]+/.test(location.pathname) ||
    location.pathname === "/upload" ||
    (workspace === "project" && new URLSearchParams(location.search).get("view") === "qa");

  useEffect(() => {
    const sync = () => {
      if (window.innerWidth <= 860) setRailCollapsed(false);
      if (window.innerWidth > 860) setMobileNavOpen(false);
    };
    sync();
    window.addEventListener("resize", sync);
    return () => window.removeEventListener("resize", sync);
  }, []);
  useEffect(() => {
    setMobileNavOpen(false);
  }, [location.pathname, location.search, authMe?.activeCompanyRole]);

  const primary = [
    {
      key: "work",
      to: "/",
      label: "工作台",
      icon: LayoutDashboard,
      allowed: can.viewHome(capabilities),
    },
    {
      key: "knowledge",
      to: "/knowledge",
      label: "知识库",
      icon: LibraryBig,
      allowed: can.viewKnowledge(capabilities),
    },
    {
      key: "project",
      to: projectPath,
      label: "项目空间",
      icon: FolderKanban,
      allowed: can.viewProject(capabilities),
    },
    {
      key: "approval",
      to: can.viewReview(capabilities) ? "/review" : "/original-access",
      label: "审批中心",
      icon: ShieldCheck,
      allowed: can.viewReview(capabilities) || can.viewOriginalAccess(capabilities),
    },
    {
      key: "admin",
      to: managers[0]?.to ?? "/",
      label: "管理中心",
      icon: Settings2,
      allowed: managers.length > 0,
    },
  ].filter((item) => item.allowed);
  const workspaceHome = primary.find((item) => item.key === workspace)?.to ?? "/";
  return (
    <div
      className={`app-layout refined-shell is-refined-workspace workspace-shell ${railCollapsed ? "is-rail-collapsed" : ""} ${mobileNavOpen ? "is-mobile-nav-open" : ""} ${focusLayout ? "is-focused-workspace" : ""}`}
      data-workspace={workspace}
    >
      <aside className="rail" aria-label="产品导航">
        <div className="rail-brand">
          <div className="rail-brand-row">
            <Link to="/" className="rail-mark">
              <img src="/moways-logo.png" alt="MOWAYS 博维咨询" width={984} height={327} />
            </Link>
            <button
              className="rail-collapse"
              type="button"
              onClick={() => setRailCollapsed((v) => !v)}
              aria-label={railCollapsed ? "展开主导航" : "折叠主导航"}
              aria-expanded={!railCollapsed}
              aria-controls="primary-navigation"
              title={railCollapsed ? "展开主导航" : "折叠主导航"}
            >
              {railCollapsed ? <PanelLeftOpen size={17} /> : <PanelLeftClose size={17} />}
            </button>
          </div>
          <span className="rail-sub">博维知识资产平台</span>
        </div>
        <nav className="rail-nav" id="primary-navigation" aria-label="主导航">
          <ul>
            {primary.map(({ key, to, label, icon: Icon }) => (
              <li key={key} className="primary-module-item">
                <Link
                  to={to}
                  aria-label={label}
                  title={railCollapsed ? label : undefined}
                  aria-current={workspace === key ? "page" : undefined}
                  className={workspace === key ? "active" : ""}
                >
                  <Icon size={18} className="rail-icon" aria-hidden="true" />
                  <span className="rail-label">{label}</span>
                </Link>
                {key === "admin" && <ModuleNavigation rail />}
              </li>
            ))}
          </ul>
        </nav>
        <div className="rail-foot">
          <ActionMenu label="帮助与更新" ariaLabel="帮助与更新">
            <Link to="/help">
              <LifeBuoy size={16} aria-hidden="true" />
              帮助
            </Link>
            <ReleaseNotesLink />
          </ActionMenu>
          <div className="rail-identity">
            <IdentityMenu />
          </div>
        </div>
      </aside>
      <div className="app-main">
        <header className="deck">
          <button
            type="button"
            className="deck-mobile-menu"
            aria-label={mobileNavOpen ? "关闭导航" : "打开导航"}
            aria-expanded={mobileNavOpen}
            onClick={() => setMobileNavOpen((v) => !v)}
          >
            <Menu size={18} aria-hidden="true" />
          </button>
          <Link to="/" className="deck-brand-link">
            <img
              className="deck-brand-logo"
              src="/moways-logo.png"
              alt="MOWAYS 博维咨询"
              width={984}
              height={327}
            />
          </Link>
          {location.pathname !== "/" && (
            <HistoryBackButton
              fallback={workspaceHome}
              className="deck-back"
              aria-label="返回上一页"
              title="返回上一页"
            >
              <ArrowLeft size={18} aria-hidden="true" />
            </HistoryBackButton>
          )}
          <nav className="deck-context" aria-label="当前位置">
            <span className="deck-eyebrow">
              <Link to={workspaceHome} aria-label={`进入${workspaceLabels[workspace]}`}>
                {workspaceLabels[workspace]}
              </Link>
              <ChevronRight size={13} aria-hidden="true" />
            </span>
            <strong className="deck-title" aria-current="page">
              {/^\/project\/[^/]+\/?$/.test(location.pathname) &&
              new URLSearchParams(location.search).get("view") === "qa"
                ? "项目问答"
                : pageTitle(location.pathname)}
            </strong>
          </nav>
          {authMe && (
            <div className="deck-actions">
              <GlobalTaskStatus />
              <NotificationBell />
            </div>
          )}
        </header>
        <main className="app-content">
          <ErrorBoundary>
            <Suspense fallback={<LoadingError loading />}>
              <Outlet />
            </Suspense>
          </ErrorBoundary>
        </main>
        <nav className="mobile-workspace-nav" aria-label="手机快捷导航">
          {primary
            .filter((item) => item.key !== "admin")
            .map(({ key, to, label, icon: Icon }) => (
              <Link
                key={key}
                to={to}
                aria-current={workspace === key ? "page" : undefined}
                className={workspace === key ? "active" : ""}
                aria-label={`底部${label}`}
              >
                <Icon size={20} aria-hidden="true" />
                <span>{mobileLabels[key] ?? label}</span>
              </Link>
            ))}
          <button
            type="button"
            aria-label="打开我的与全部功能"
            aria-expanded={mobileNavOpen}
            onClick={() => setMobileNavOpen((v) => !v)}
          >
            <UserRound size={20} aria-hidden="true" />
            <span>我的</span>
          </button>
        </nav>
      </div>
      <DetailDrawer
        portal
        open={mobileNavOpen}
        title="我的"
        onClose={() => setMobileNavOpen(false)}
        className="mobile-account-drawer"
      >
        <IdentityMenu />
        <nav className="account-navigation" aria-label="全部功能">
          {can.viewProject(capabilities) && (
            <Link to={projectPath} onClick={() => setMobileNavOpen(false)}>
              <FolderKanban size={17} aria-hidden="true" />
              我的项目
            </Link>
          )}
          {[
            ...permittedEntries(knowledgeEntries, capabilities),
            ...permittedEntries(approvalEntries, capabilities),
          ].map((entry) => (
            <Link key={entry.to} to={entry.to}>
              {entry.label}
              <ChevronRight size={15} aria-hidden="true" />
            </Link>
          ))}
          {can.viewWorkbuddy(capabilities) && (
            <Link to="/my/workbuddy">
              个人工具接入
              <ChevronRight size={15} aria-hidden="true" />
            </Link>
          )}
          {managers.length > 0 && (
            <>
              <h3>管理中心</h3>
              {managers.map((entry) => (
                <Link key={entry.to} to={entry.to}>
                  {entry.label}
                  <ChevronRight size={15} aria-hidden="true" />
                </Link>
              ))}
            </>
          )}
          <h3>帮助与更新</h3>
          <Link to="/help">帮助中心</Link>
          <ReleaseNotesLink />
        </nav>
      </DetailDrawer>
    </div>
  );
}

export default function AppLayout() {
  return (
    <AuthProvider>
      <LoginGate>
        <WorkbenchProvider>
          <SafeNavigationProvider>
            <AppShell />
          </SafeNavigationProvider>
        </WorkbenchProvider>
      </LoginGate>
    </AuthProvider>
  );
}
