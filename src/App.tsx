import { lazy } from "react";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import AppLayout from "./layouts/AppLayout";
import ErrorBoundary from "./components/ErrorBoundary";
import NotFoundPage from "./pages/NotFoundPage";

// 路由级代码分割：每个页面按需动态 import，Vite 自动为其切分 chunk，首屏不再一次性
// 加载全部 18 个页面。Suspense fallback 与内层 ErrorBoundary 放在 AppLayout 的 Outlet
// 周围（见 AppLayout.tsx），使页面 chunk 加载 / 崩溃时左侧导航与顶栏保持不动。
// AppLayout、ErrorBoundary、NotFoundPage 属应用外壳，保持静态导入。
const HomeDashboardPage = lazy(() => import("./pages/HomeDashboardPage"));
const KnowledgeListPage = lazy(() => import("./pages/KnowledgeListPage"));
const KnowledgeDetailPage = lazy(() => import("./pages/KnowledgeDetailPage"));
const MyKnowledgePage = lazy(() => import("./pages/MyKnowledgePage"));
const UploadPage = lazy(() => import("./pages/UploadPage"));
const AdminIngestPage = lazy(() => import("./pages/AdminIngestPage"));
const AdminWecomScanPage = lazy(() => import("./pages/AdminWecomScanPage"));
const AdminWeKnoraModelsPage = lazy(() => import("./pages/AdminWeKnoraModelsPage"));
const AdminAuditPage = lazy(() => import("./pages/AdminAuditPage"));
const AdminAuthSecurityPage = lazy(() => import("./pages/AdminAuthSecurityPage"));
const AdminAlertSettingsPage = lazy(() => import("./pages/AdminAlertSettingsPage"));
const AdminPeoplePage = lazy(() => import("./pages/AdminPeoplePage"));
const AdminPermissionsPage = lazy(() => import("./pages/AdminPermissionsPage"));
const ReviewPage = lazy(() => import("./pages/ReviewPage"));
const OriginalAccessPage = lazy(() => import("./pages/OriginalAccessPage"));
const ProjectKnowledgePage = lazy(() => import("./pages/ProjectKnowledgePage"));
const ProjectSettingsPage = lazy(() => import("./pages/ProjectSettingsPage"));
const HelpPage = lazy(() => import("./pages/HelpPage"));

export default function App() {
  return (
    <BrowserRouter>
      {/* 全局兜底：捕获连 AppLayout 外壳在内的渲染崩溃。内层另有针对内容区的 ErrorBoundary。 */}
      <ErrorBoundary>
        <Routes>
          <Route element={<AppLayout />}>
            <Route index element={<HomeDashboardPage />} />
            <Route path="knowledge" element={<KnowledgeListPage />} />
            <Route path="knowledge/:id" element={<KnowledgeDetailPage />} />
            <Route path="my/knowledge" element={<MyKnowledgePage />} />
            <Route path="upload" element={<UploadPage />} />
            <Route path="admin/ingest" element={<AdminIngestPage />} />
            <Route path="admin/wecom-scan" element={<AdminWecomScanPage />} />
            <Route path="admin/weknora-models" element={<AdminWeKnoraModelsPage />} />
            <Route path="admin/audit" element={<AdminAuditPage />} />
            <Route path="admin/auth-security" element={<AdminAuthSecurityPage />} />
            <Route path="admin/alert-settings" element={<AdminAlertSettingsPage />} />
            <Route path="admin/people" element={<AdminPeoplePage />} />
            <Route path="admin/permissions" element={<AdminPermissionsPage />} />
            <Route path="review" element={<ReviewPage />} />
            <Route path="original-access" element={<OriginalAccessPage />} />
            <Route path="project/:id/knowledge" element={<ProjectKnowledgePage />} />
            <Route path="project/:id/settings" element={<ProjectSettingsPage />} />
            <Route path="help" element={<HelpPage />} />
            {/* 未知路由兜底（渲染在 AppLayout 内，导航仍可用）。 */}
            <Route path="*" element={<NotFoundPage />} />
          </Route>
        </Routes>
      </ErrorBoundary>
    </BrowserRouter>
  );
}
