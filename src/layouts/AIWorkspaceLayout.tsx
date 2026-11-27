import { Suspense } from "react";
import { Outlet } from "react-router-dom";
import { AuthProvider, useAuth } from "../auth/AuthContext";
import LoginGate from "../auth/LoginGate";
import ErrorBoundary from "../components/ErrorBoundary";
import LoadingError from "../components/LoadingError";
import { SafeNavigationProvider } from "../routing/SafeNavigation";

function WorkspaceIdentity() {
  const { authMe } = useAuth();
  return (
    <ErrorBoundary key={`${authMe?.userId}:${authMe?.activeCompanyRole}`}>
      <Suspense fallback={<LoadingError loading loadingTitle="正在打开 AI 工作空间…" />}>
        <Outlet />
      </Suspense>
    </ErrorBoundary>
  );
}

/** Same authenticated origin, independently mounted product shell. */
export default function AIWorkspaceLayout() {
  return (
    <AuthProvider>
      <LoginGate>
        <SafeNavigationProvider>
          <WorkspaceIdentity />
        </SafeNavigationProvider>
      </LoginGate>
    </AuthProvider>
  );
}
