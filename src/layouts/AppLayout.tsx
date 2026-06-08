import { NavLink, Outlet } from "react-router-dom";
import {
  LayoutDashboard, LibraryBig, UserRound, FileCheck2, ShieldCheck, KeyRound, FolderKanban,
  SlidersHorizontal, Inbox, ScanLine, Cpu, ScrollText, ShieldAlert, BellRing,
  KeySquare, Users, LifeBuoy, type LucideIcon,
} from "lucide-react";
import IdentityMenu from "../components/IdentityMenu";
import logoUrl from "../assets/moways-logo.png";
import "./AppLayout.css";
import "../styles/workbench.css";
import "../styles/workbench-home-admin.css";

type NavItem = { to: string; label: string; icon: LucideIcon; end?: boolean };
type NavGroup = { no: string; label: string; items: NavItem[] };

const homeItem: NavItem = { to: "/", label: "今日工作台", icon: LayoutDashboard, end: true };

const navGroups: NavGroup[] = [
  {
    no: "01",
    label: "业务功能",
    items: [
      { to: "/knowledge", label: "知识资产库", icon: LibraryBig },
      { to: "/my/knowledge", label: "个人知识", icon: UserRound },
      { to: "/upload", label: "资产化确认", icon: FileCheck2 },
      { to: "/review", label: "升级审核", icon: ShieldCheck },
      { to: "/original-access", label: "原文访问", icon: KeyRound },
      { to: "/project/current/knowledge", label: "项目看板", icon: FolderKanban },
      { to: "/project/current/settings", label: "项目设置", icon: SlidersHorizontal },
    ],
  },
  {
    no: "02",
    label: "管理后台",
    items: [
      { to: "/admin/ingest", label: "入库管理", icon: Inbox },
      { to: "/admin/wecom-scan", label: "微盘扫描", icon: ScanLine },
      { to: "/admin/weknora-models", label: "模型配置", icon: Cpu },
      { to: "/admin/audit", label: "审计日志", icon: ScrollText },
      { to: "/admin/auth-security", label: "登录风控", icon: ShieldAlert },
      { to: "/admin/alert-settings", label: "告警设置", icon: BellRing },
      { to: "/admin/permissions", label: "权限规则", icon: KeySquare },
      { to: "/admin/people", label: "人员权限", icon: Users },
    ],
  },
  {
    no: "03",
    label: "帮助",
    items: [{ to: "/help", label: "使用说明", icon: LifeBuoy }],
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

export default function AppLayout() {
  return (
    <div className="app-layout">
      <aside className="rail">
        <div className="rail-brand">
          <span className="rail-mark">MOWAYS</span>
          <span className="rail-sub">博维咨询 · 知识资产工作台</span>
        </div>
        <nav className="rail-nav">
          <div className="rail-group rail-group-lead">
            <ul><RailLink item={homeItem} /></ul>
          </div>
          {navGroups.map((group) => (
            <div key={group.label} className="rail-group">
              <div className="rail-group-label">
                <span className="rail-group-no">{group.no}</span>
                {group.label}
              </div>
              <ul>
                {group.items.map((item) => <RailLink key={item.to} item={item} />)}
              </ul>
            </div>
          ))}
        </nav>
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
          <Outlet />
        </main>
      </div>
    </div>
  );
}
