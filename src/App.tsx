import { lazy } from "react";
import { BrowserRouter, Navigate, Routes, Route } from "react-router-dom";
import AppLayout from "./layouts/AppLayout";
import ErrorBoundary from "./components/ErrorBoundary";
import NotFoundPage from "./pages/NotFoundPage";
import RouteGuard from "./auth/RouteGuard";
import { can } from "./auth/permissions";

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
const AdminCompanyKbPage = lazy(() => import("./pages/AdminCompanyKbPage"));
const AdminPermissionsPage = lazy(() => import("./pages/AdminPermissionsPage"));
const AdminNamingRulesPage = lazy(() => import("./pages/AdminNamingRulesPage"));
const ReviewPage = lazy(() => import("./pages/ReviewPage"));
const ReviewCompletedPage = lazy(() => import("./pages/ReviewCompletedPage"));
const OriginalAccessPage = lazy(() => import("./pages/OriginalAccessPage"));
const ProjectOverviewPage = lazy(() => import("./pages/ProjectOverviewPage"));
const ProjectKnowledgePage = lazy(() => import("./pages/ProjectKnowledgePage"));
const ProjectSettingsPage = lazy(() => import("./pages/ProjectSettingsPage"));
const HelpPage = lazy(() => import("./pages/HelpPage"));

export default function App() {
  return (
    <BrowserRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      {/* 全局兜底：捕获连 AppLayout 外壳在内的渲染崩溃。内层另有针对内容区的 ErrorBoundary。 */}
      <ErrorBoundary>
        <Routes>
          <Route element={<AppLayout />}>
            <Route index element={<HomeDashboardPage />} />
            {/* 守卫与导航共用 can.* 判定：无权直接渲染「无此入口」态，不让页面先发请求。
                后端仍是权威：绕过前端直达接口照常 403/404。 */}
            <Route
              path="knowledge"
              element={
                <RouteGuard cap={can.viewKnowledge}>
                  <KnowledgeListPage />
                </RouteGuard>
              }
            />
            <Route
              path="knowledge/:id"
              element={
                <RouteGuard cap={can.viewKnowledge}>
                  <KnowledgeDetailPage />
                </RouteGuard>
              }
            />
            <Route
              path="my/knowledge"
              element={
                <RouteGuard cap={can.viewMyKnowledge}>
                  <MyKnowledgePage />
                </RouteGuard>
              }
            />
            <Route
              path="upload"
              element={
                <RouteGuard cap={can.viewUpload}>
                  <UploadPage />
                </RouteGuard>
              }
            />
            <Route path="admin" element={<Navigate to="/admin/ingest" replace />} />
            <Route
              path="admin/ingest"
              element={
                <RouteGuard cap={can.viewIngestAdmin}>
                  <AdminIngestPage />
                </RouteGuard>
              }
            />
            <Route
              path="admin/wecom-scan"
              element={
                <RouteGuard cap={can.viewWecomScan}>
                  <AdminWecomScanPage />
                </RouteGuard>
              }
            />
            <Route
              path="admin/weknora-models"
              element={
                <RouteGuard cap={can.viewModels}>
                  <AdminWeKnoraModelsPage />
                </RouteGuard>
              }
            />
            <Route
              path="admin/audit"
              element={
                <RouteGuard cap={can.viewAudit}>
                  <AdminAuditPage />
                </RouteGuard>
              }
            />
            <Route
              path="admin/auth-security"
              element={
                <RouteGuard cap={can.viewAuthSecurity}>
                  <AdminAuthSecurityPage />
                </RouteGuard>
              }
            />
            <Route
              path="admin/alert-settings"
              element={
                <RouteGuard cap={can.viewAlerts}>
                  <AdminAlertSettingsPage />
                </RouteGuard>
              }
            />
            <Route
              path="admin/people"
              element={
                <RouteGuard cap={can.viewPeople}>
                  <AdminPeoplePage />
                </RouteGuard>
              }
            />
            <Route
              path="admin/company-kb"
              element={
                <RouteGuard cap={can.viewCompanyKnowledge}>
                  <AdminCompanyKbPage />
                </RouteGuard>
              }
            />
            <Route
              path="admin/naming-rules"
              element={
                <RouteGuard cap={can.viewNamingRules}>
                  <AdminNamingRulesPage />
                </RouteGuard>
              }
            />
            <Route
              path="admin/permissions"
              element={
                <RouteGuard cap={can.viewPermissions}>
                  <AdminPermissionsPage />
                </RouteGuard>
              }
            />
            <Route
              path="review"
              element={
                <RouteGuard cap={can.viewReview}>
                  <ReviewPage />
                </RouteGuard>
              }
            />
            <Route
              path="review/completed"
              element={
                <RouteGuard cap={can.viewReview}>
                  <ReviewCompletedPage />
                </RouteGuard>
              }
            />
            <Route
              path="original-access"
              element={
                <RouteGuard cap={can.viewOriginalAccess}>
                  <OriginalAccessPage />
                </RouteGuard>
              }
            />
            <Route
              path="project/:id"
              element={
                <RouteGuard cap={can.viewProject}>
                  <ProjectOverviewPage />
                </RouteGuard>
              }
            />
            <Route
              path="project/:id/knowledge"
              element={
                <RouteGuard cap={can.viewProject}>
                  <ProjectKnowledgePage />
                </RouteGuard>
              }
            />
            <Route
              path="project/:id/settings"
              element={
                <RouteGuard cap={can.viewProject}>
                  <ProjectSettingsPage />
                </RouteGuard>
              }
            />
            <Route path="help" element={<HelpPage />} />
            {/* 未知路由兜底（渲染在 AppLayout 内，导航仍可用）。 */}
            <Route path="*" element={<NotFoundPage />} />
          </Route>
        </Routes>
      </ErrorBoundary>
    </BrowserRouter>
  );
}
