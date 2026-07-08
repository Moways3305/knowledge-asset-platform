import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import AppLayout from "./AppLayout";

vi.mock("../auth/AuthContext", () => ({
  AuthProvider: ({ children }: { children: ReactNode }) => <>{children}</>,
  useAuth: () => ({
    capabilities: {
      isAuthenticated: false,
      isActive: false,
      isBusinessUser: false,
      canDiscoverL5: false,
      isAdmin: false,
      isGovernance: false,
      companyRoles: [],
      projectIds: [],
    },
    authMe: null,
    status: "anonymous",
    setAuthMe: vi.fn(),
    reload: vi.fn(),
  }),
}));

describe("AppLayout brand chrome", () => {
  it("shows Kivo as the product name with knowledge-platform subtitle", () => {
    render(
      <MemoryRouter>
        <Routes>
          <Route element={<AppLayout />}>
            <Route index element={<div>home</div>} />
          </Route>
        </Routes>
      </MemoryRouter>,
    );

    expect(screen.getByText("Kivo")).toBeInTheDocument();
    expect(screen.getByText("博维知识资产平台")).toBeInTheDocument();
  });
});
