import { useEffect, type ReactNode } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "./AuthContext";
import { consumeLoginReturn } from "./loginReturn";
import LoginPage from "../pages/LoginPage";

export default function LoginGate({ children }: { children: ReactNode }) {
  const { status } = useAuth();
  const location = useLocation();
  const navigate = useNavigate();
  useEffect(() => {
    if (status !== "authenticated") return;
    const target = consumeLoginReturn();
    if (target && location.pathname === "/") navigate(target, { replace: true });
  }, [status, location.pathname, navigate]);
  // Keep the requested URL intact. No protected page/provider mounts before auth.
  return status === "authenticated" ? children : <LoginPage />;
}
