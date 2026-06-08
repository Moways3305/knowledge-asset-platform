import { BrowserRouter, Routes, Route } from "react-router-dom";
import AppLayout from "./layouts/AppLayout";
import HomeDashboardPage from "./pages/HomeDashboardPage";
import KnowledgeListPage from "./pages/KnowledgeListPage";
import KnowledgeDetailPage from "./pages/KnowledgeDetailPage";
import UploadPage from "./pages/UploadPage";
import AdminIngestPage from "./pages/AdminIngestPage";
import ReviewPage from "./pages/ReviewPage";
import ProjectKnowledgePage from "./pages/ProjectKnowledgePage";
import AdminAuditPage from "./pages/AdminAuditPage";
import AdminAuthSecurityPage from "./pages/AdminAuthSecurityPage";
import AdminAlertSettingsPage from "./pages/AdminAlertSettingsPage";
import AdminPeoplePage from "./pages/AdminPeoplePage";
import AdminPermissionsPage from "./pages/AdminPermissionsPage";
import AdminWecomScanPage from "./pages/AdminWecomScanPage";
import AdminWeKnoraModelsPage from "./pages/AdminWeKnoraModelsPage";
import ProjectSettingsPage from "./pages/ProjectSettingsPage";
import MyKnowledgePage from "./pages/MyKnowledgePage";
import OriginalAccessPage from "./pages/OriginalAccessPage";
import HelpPage from "./pages/HelpPage";

export default function App() {
  return (
    <BrowserRouter>
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
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
