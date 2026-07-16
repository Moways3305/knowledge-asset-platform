import { describe, expect, it } from "vitest";

const forbiddenParallelModules = import.meta.glob(
  ["../legacy/**/*", "../new-*/**/*", "../v2/**/*"],
  { eager: true, query: "?raw", import: "default" },
);

const productionUiModules = import.meta.glob(["../{pages,components,auth}/**/*.{ts,tsx}"], {
  eager: true,
  query: "?raw",
  import: "default",
}) as Record<string, string>;

const styleModules = import.meta.glob(["../{layouts,styles}/**/*.css"], {
  eager: true,
  query: "?raw",
  import: "default",
}) as Record<string, string>;

describe("frontend architecture baseline", () => {
  it("forbids parallel legacy, new-* and v2 frontend directories", () => {
    expect(Object.keys(forbiddenParallelModules)).toEqual([]);
  });

  it("keeps the application shell owned by AppLayout only", () => {
    for (const [file, source] of Object.entries(productionUiModules)) {
      expect(source, file).not.toContain('className="app-layout"');
      expect(source, file).not.toContain('className="rail-nav"');
      expect(source, file).not.toContain("<Outlet");
    }
  });

  it("keeps retired topbar and sidebar shell selectors out of active styles", () => {
    const styles = Object.values(styleModules).join("\n");
    expect(styles).not.toContain(".app-topbar");
    expect(styles).not.toContain(".app-sidebar");
    expect(styles).not.toContain(".sidebar-brand");
  });

  it("does not cache identity or permission state in browser storage", () => {
    const scannedFiles = Object.keys(productionUiModules);
    expect(scannedFiles.some((file) => file.endsWith("/auth/AuthContext.tsx"))).toBe(true);
    expect(scannedFiles.some((file) => file.endsWith("/auth/permissions.ts"))).toBe(true);
    for (const [file, source] of Object.entries(productionUiModules)) {
      expect(source, file).not.toMatch(/\b(?:localStorage|sessionStorage)\b/);
    }
  });

  it("keeps one real project settings page without the retired KPI shell or identity fields", () => {
    const source = productionUiModules["../pages/ProjectSettingsPage.tsx"];
    const styles = Object.values(styleModules).join("\n");
    expect(source).toBeDefined();
    expect(source).toContain("fetchProjectSettings");
    expect(source).toContain("fetchProjectMembers");
    expect(source).toContain("fetchReviews");
    expect(source).not.toContain('className="kl-header"');
    expect(source).not.toContain('className="ps-page"');
    expect(source).not.toContain("member.email");
    expect(source).not.toContain("member.company_roles");
    expect(styles).not.toContain(".ps-page");
    expect(styles).not.toContain(".ps-kpi-on");
    expect(styles).not.toContain(".ps-table");
  });
});
