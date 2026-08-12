import { describe, expect, it } from "vitest";
import * as ts from "typescript";

type RouteContract = {
  route: string;
  component: string;
  guard: string;
  owners: string[];
  apiModules: string[];
  allowedTimerOwners?: string[];
};

type BusinessOptionContract = {
  route: string;
  owner: string;
  option: "model" | "project" | "role" | "status";
  source:
    | { kind: "runtime"; symbol: string }
    | { kind: "static-product-exception"; registry: string; reason: string };
};

const routes: RouteContract[] = [
  {
    route: "/",
    component: "HomeDashboardPage",
    guard: "public",
    owners: ["pages/HomeDashboardPage.tsx", "workbench/WorkbenchContext.tsx"],
    apiModules: ["workbench", "admin", "project"],
  },
  {
    route: "/knowledge",
    component: "KnowledgeListPage",
    guard: "viewKnowledge",
    owners: ["pages/KnowledgeListPage.tsx"],
    apiModules: ["knowledge"],
  },
  {
    route: "/knowledge/:id",
    component: "KnowledgeDetailPage",
    guard: "viewKnowledge",
    owners: ["pages/KnowledgeDetailPage.tsx", "pages/knowledge/OnlyOfficePreview.tsx"],
    apiModules: ["http", "knowledge"],
    allowedTimerOwners: ["pages/knowledge/OnlyOfficePreview.tsx"],
  },
  {
    route: "/my/knowledge",
    component: "MyKnowledgePage",
    guard: "viewMyKnowledge",
    owners: [
      "pages/MyKnowledgePage.tsx",
      "hooks/useModelSelection.ts",
      "components/WorkbuddyAccessCard.tsx",
    ],
    apiModules: ["auth", "bulk", "http", "knowledge", "personal", "weknoraModels", "workbuddy"],
  },
  {
    route: "/upload",
    component: "UploadPage",
    guard: "viewUpload",
    owners: [
      "pages/upload/useUploadFlow.ts",
      "pages/upload/useUploadIntake.ts",
      "pages/upload/usePendingIngest.ts",
      "pages/upload/useIngestConfirmation.ts",
      "hooks/useModelSelection.ts",
    ],
    apiModules: ["auth", "bulk", "http", "ingest", "naming", "weknoraModels"],
  },
  {
    route: "/admin/ingest",
    component: "AdminIngestPage",
    guard: "viewIngestAdmin",
    owners: ["pages/AdminIngestPage.tsx"],
    apiModules: ["admin", "http", "ingest"],
  },
  {
    route: "/admin/wecom-scan",
    component: "AdminWecomScanPage",
    guard: "viewWecomScan",
    owners: ["pages/AdminWecomScanPage.tsx", "pages/wecomScan/WecomScanConfigForm.tsx"],
    apiModules: ["admin", "http"],
  },
  {
    route: "/admin/weknora-models",
    component: "AdminWeKnoraModelsPage",
    guard: "viewModels",
    owners: ["pages/AdminWeKnoraModelsPage.tsx", "components/UnifiedModelConnectionsSection.tsx"],
    apiModules: ["admin", "http", "modelConnections"],
  },
  {
    route: "/admin/audit",
    component: "AdminAuditPage",
    guard: "viewAudit",
    owners: ["pages/AdminAuditPage.tsx"],
    apiModules: ["admin", "http"],
  },
  {
    route: "/admin/auth-security",
    component: "AdminAuthSecurityPage",
    guard: "viewAuthSecurity",
    owners: ["pages/AdminAuthSecurityPage.tsx"],
    apiModules: ["admin", "http"],
  },
  {
    route: "/admin/alert-settings",
    component: "AdminAlertSettingsPage",
    guard: "viewAlerts",
    owners: ["pages/AdminAlertSettingsPage.tsx"],
    apiModules: ["admin", "http"],
  },
  {
    route: "/admin/people",
    component: "AdminPeoplePage",
    guard: "viewPeople",
    owners: ["pages/AdminPeoplePage.tsx"],
    apiModules: ["admin", "http"],
  },
  {
    route: "/admin/naming-rules",
    component: "AdminNamingRulesPage",
    guard: "viewNamingRules",
    owners: ["pages/AdminNamingRulesPage.tsx"],
    apiModules: ["http", "naming"],
  },
  {
    route: "/admin/company-kb",
    component: "AdminCompanyKbPage",
    guard: "viewCompanyKnowledge",
    owners: ["pages/AdminCompanyKbPage.tsx"],
    apiModules: ["admin", "http"],
  },
  {
    route: "/admin/permissions",
    component: "AdminPermissionsPage",
    guard: "viewPermissions",
    owners: ["pages/AdminPermissionsPage.tsx"],
    apiModules: ["admin", "auth", "http"],
  },
  {
    route: "/review",
    component: "ReviewPage",
    guard: "viewReview",
    owners: ["pages/ReviewPage.tsx"],
    apiModules: ["bulk", "http", "review"],
  },
  {
    route: "/review/completed",
    component: "ReviewCompletedPage",
    guard: "viewReview",
    owners: ["pages/ReviewCompletedPage.tsx"],
    apiModules: ["http", "review"],
  },
  {
    route: "/original-access",
    component: "OriginalAccessPage",
    guard: "viewOriginalAccess",
    owners: ["pages/OriginalAccessPage.tsx"],
    apiModules: ["bulk", "http", "knowledge"],
  },
  {
    route: "/project/:id",
    component: "ProjectOverviewPage",
    guard: "viewProject",
    owners: ["pages/ProjectOverviewPage.tsx"],
    apiModules: ["admin", "http", "project"],
  },
  {
    route: "/project/:id/knowledge",
    component: "ProjectKnowledgePage",
    guard: "viewProject",
    owners: ["pages/ProjectKnowledgePage.tsx"],
    apiModules: ["bulk", "knowledge", "project", "review"],
  },
  {
    route: "/project/:id/settings",
    component: "ProjectSettingsPage",
    guard: "viewProject",
    owners: ["pages/ProjectSettingsPage.tsx"],
    apiModules: ["http", "project", "review"],
  },
  {
    route: "/help",
    component: "HelpPage",
    guard: "public",
    owners: [],
    apiModules: [],
  },
];

const businessOptions: BusinessOptionContract[] = [
  {
    route: "/project/:id",
    owner: "pages/ProjectOverviewPage.tsx",
    option: "project",
    source: { kind: "runtime", symbol: "fetchProjects" },
  },
  {
    route: "/knowledge",
    owner: "pages/KnowledgeListPage.tsx",
    option: "project",
    source: { kind: "runtime", symbol: "useAuth" },
  },
  {
    route: "/project/:id/knowledge",
    owner: "pages/ProjectKnowledgePage.tsx",
    option: "project",
    source: { kind: "runtime", symbol: "useAuth" },
  },
  {
    route: "/project/:id/knowledge",
    owner: "pages/ProjectKnowledgePage.tsx",
    option: "model",
    source: { kind: "runtime", symbol: "fetchProjectQaModelOptions" },
  },
  {
    route: "/project/:id/settings",
    owner: "pages/ProjectSettingsPage.tsx",
    option: "role",
    source: {
      kind: "static-product-exception",
      registry: "PROJECT_ROLE_OPTIONS",
      reason: "Matches the backend ProjectRole product enum.",
    },
  },
  {
    route: "/admin/people",
    owner: "pages/AdminPeoplePage.tsx",
    option: "role",
    source: {
      kind: "static-product-exception",
      registry: "COMPANY_ROLE_OPTIONS",
      reason: "Matches the governed company-role enum exposed by the people API.",
    },
  },
  {
    route: "/admin/people",
    owner: "pages/AdminPeoplePage.tsx",
    option: "status",
    source: {
      kind: "static-product-exception",
      registry: "USER_STATUS_OPTIONS",
      reason: "Matches the active/inactive user lifecycle enum enforced by the backend.",
    },
  },
];

const repairedBusinessOptionDefects = [
  {
    id: "PBC-62-project-qa-demo-models",
    owner: "pages/ProjectKnowledgePage.tsx",
    forbiddenValues: ["deepseek-r1", "qwen-enterprise", "DeepSeek-R1 内网版", "通义千问企业版"],
  },
];

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

const sourceModules = import.meta.glob(
  ["../App.tsx", "../{pages,components,hooks,workbench}/**/*.{ts,tsx}"],
  { eager: true, query: "?raw", import: "default" },
) as Record<string, string>;

const source = (file: string) => {
  const value = sourceModules[`../${file}`];
  expect(value, `missing takeover owner: ${file}`).toBeDefined();
  return value;
};

function parse(file: string, text: string) {
  return ts.createSourceFile(file, text, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
}

function importedApiModules(file: string): string[] {
  const modules = new Set<string>();
  for (const statement of parse(file, source(file)).statements) {
    if (!ts.isImportDeclaration(statement) || !ts.isStringLiteral(statement.moduleSpecifier))
      continue;
    const match = statement.moduleSpecifier.text.match(/\/api\/([^/]+)$/);
    if (match) modules.add(match[1]);
  }
  return [...modules].sort();
}

function appRouteOwnership() {
  const app = parse("App.tsx", source("App.tsx"));
  const lazyPages = new Map<string, string>();
  const ownership = new Map<string, { component: string; guard: string }>();

  const collectLazyPages = (node: ts.Node) => {
    if (ts.isVariableDeclaration(node) && ts.isIdentifier(node.name) && node.initializer) {
      let importedPage: string | undefined;
      const findImport = (child: ts.Node) => {
        if (
          ts.isCallExpression(child) &&
          child.expression.kind === ts.SyntaxKind.ImportKeyword &&
          child.arguments[0] &&
          ts.isStringLiteral(child.arguments[0])
        ) {
          importedPage = child.arguments[0].text;
        }
        ts.forEachChild(child, findImport);
      };
      findImport(node.initializer);
      if (importedPage?.startsWith("./pages/")) lazyPages.set(node.name.text, importedPage);
    }
    ts.forEachChild(node, collectLazyPages);
  };
  collectLazyPages(app);

  const visitRoutes = (node: ts.Node) => {
    if (ts.isJsxSelfClosingElement(node) && node.tagName.getText(app) === "Route") {
      const attributes = node.attributes.properties.filter(ts.isJsxAttribute);
      const pathAttribute = attributes.find((item) => item.name.getText(app) === "path");
      const isIndex = attributes.some((item) => item.name.getText(app) === "index");
      const pathValue = pathAttribute?.initializer;
      const route = isIndex
        ? "/"
        : pathValue && ts.isStringLiteral(pathValue)
          ? `/${pathValue.text}`
          : undefined;
      if (route && route !== "/*") {
        let component = "";
        let guard = "public";
        const findOwnership = (child: ts.Node) => {
          if (ts.isJsxSelfClosingElement(child)) {
            const name = child.tagName.getText(app);
            if (lazyPages.has(name)) component = name;
          }
          if (ts.isPropertyAccessExpression(child) && child.expression.getText(app) === "can") {
            guard = child.name.text;
          }
          ts.forEachChild(child, findOwnership);
        };
        findOwnership(node);
        ownership.set(route, { component, guard });
      }
    }
    ts.forEachChild(node, visitRoutes);
  };
  visitRoutes(app);
  return ownership;
}

function staticStringRecordValues(file: string, variableName: string): string[] {
  const tree = parse(file, source(file));
  const values: string[] = [];
  const visit = (node: ts.Node) => {
    if (
      ts.isVariableDeclaration(node) &&
      ts.isIdentifier(node.name) &&
      node.name.text === variableName &&
      node.initializer &&
      ts.isObjectLiteralExpression(node.initializer)
    ) {
      for (const property of node.initializer.properties) {
        if (ts.isPropertyAssignment(property) && ts.isStringLiteral(property.initializer)) {
          values.push(property.initializer.text);
        }
      }
    }
    ts.forEachChild(node, visit);
  };
  visit(tree);
  return values;
}

describe("frontend route takeover gate", () => {
  it("assigns every formal App route to the registered page and capability", () => {
    const actual = appRouteOwnership();
    expect(actual.size).toBe(22);
    expect([...actual.keys()].sort()).toEqual(routes.map((item) => item.route).sort());
    for (const contract of routes) {
      expect(actual.get(contract.route), contract.route).toEqual({
        component: contract.component,
        guard: contract.guard,
      });
    }
  });

  it("keeps every static workbench operation target on a registered App route", () => {
    const registeredRoutes = appRouteOwnership();
    const operationTargets = staticStringRecordValues(
      "pages/HomeDashboardPage.tsx",
      "OPERATION_ROUTE",
    );

    expect(operationTargets.length).toBeGreaterThan(0);
    for (const target of operationTargets) {
      expect(registeredRoutes.has(target), target).toBe(true);
    }
  });

  it("routes cross-scope KB initialization failures to the protected mapping configuration page", () => {
    const dashboard = source("pages/HomeDashboardPage.tsx");
    const targetPage = source("pages/AdminWeKnoraModelsPage.tsx");

    expect(dashboard).toContain('item.scope === "company"');
    expect(dashboard).toContain('item.scope === "personal"');
    expect(dashboard).toContain('item.scope === "project"');
    expect(dashboard).toContain('return "/admin/weknora-models"');
    expect(targetPage).toContain("知识库配置");
    expect(targetPage).toContain('init_failed: "初始化异常"');
    expect(targetPage).toContain('title="管理知识库配置"');
  });

  it("keeps every top-level production Page reachable or explicitly exempted", () => {
    const pageFiles = Object.keys(sourceModules)
      .filter((key) => /^\.\.\/pages\/[^/]+Page\.tsx$/.test(key))
      .map((key) => key.split("/").slice(-1)[0]?.replace(".tsx", ""))
      .filter((name): name is string => Boolean(name))
      .sort();
    const registered = [...routes.map((item) => item.component), "NotFoundPage"].sort();
    expect(pageFiles).toEqual(registered);
  });

  it("traces every data route to its registered real API modules", () => {
    for (const contract of routes) {
      const actual = new Set(contract.owners.flatMap(importedApiModules));
      expect([...actual].sort(), contract.route).toEqual([...contract.apiModules].sort());
      if (contract.route !== "/help") expect(actual.size, contract.route).toBeGreaterThan(0);
    }
  });

  it("rejects test/demo imports and unregistered timers in production owners", () => {
    for (const contract of routes) {
      const files = new Set([`pages/${contract.component}.tsx`, ...contract.owners]);
      for (const file of files) {
        const tree = parse(file, source(file));
        const allowedTimer = contract.allowedTimerOwners?.includes(file) ?? false;
        const visit = (node: ts.Node) => {
          if (ts.isImportDeclaration(node) && ts.isStringLiteral(node.moduleSpecifier)) {
            expect(node.moduleSpecifier.text, file).not.toMatch(
              /(?:^|\/)(?:__mocks__|mocks?|demos?|fixtures?)(?:\/|$)|@testing-library|vitest/,
            );
          }
          if (
            ts.isCallExpression(node) &&
            ts.isIdentifier(node.expression) &&
            node.expression.text === "setTimeout"
          ) {
            expect(allowedTimer, `${file} must register a legitimate timer`).toBe(true);
          }
          ts.forEachChild(node, visit);
        };
        visit(tree);
      }
    }
  });

  it("requires high-risk business options to declare a real source or product exception", () => {
    for (const contract of businessOptions) {
      expect(
        routes.some((route) => route.route === contract.route),
        contract.route,
      ).toBe(true);
      const ownerSource = source(contract.owner);
      if (contract.source.kind === "runtime") {
        expect(ownerSource, `${contract.route}:${contract.option}`).toContain(
          contract.source.symbol,
        );
      } else {
        expect(contract.source.reason.trim().length).toBeGreaterThan(0);
        expect(ownerSource, `${contract.route}:${contract.option}`).toContain(
          contract.source.registry,
        );
      }
    }
  });

  it("keeps repaired demo business options out of production owners", () => {
    for (const defect of repairedBusinessOptionDefects) {
      const ownerSource = source(defect.owner);
      for (const value of defect.forbiddenValues) {
        expect(ownerSource, `${defect.id}:${value}`).not.toContain(value);
      }
    }
  });

  it("forbids parallel legacy, new-* and v2 frontend directories", () => {
    expect(Object.keys(forbiddenParallelModules)).toEqual([]);
  });

  it("keeps the application shell owned by AppLayout only", () => {
    for (const [file, moduleSource] of Object.entries(productionUiModules)) {
      expect(moduleSource, file).not.toContain('className="app-layout"');
      expect(moduleSource, file).not.toContain('className="rail-nav"');
      expect(moduleSource, file).not.toContain("<Outlet");
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
    for (const [file, moduleSource] of Object.entries(productionUiModules)) {
      expect(moduleSource, file).not.toMatch(/\b(?:localStorage|sessionStorage)\b/);
    }
  });

  it("keeps project settings on real APIs without retired identity-bearing UI", () => {
    const projectSettingsSource = productionUiModules["../pages/ProjectSettingsPage.tsx"];
    const styles = Object.values(styleModules).join("\n");
    expect(projectSettingsSource).toBeDefined();
    expect(projectSettingsSource).toContain("fetchProjectSettings");
    expect(projectSettingsSource).toContain("fetchProjectMembers");
    expect(projectSettingsSource).toContain("fetchReviews");
    expect(projectSettingsSource).not.toContain('className="kl-header"');
    expect(projectSettingsSource).not.toContain('className="ps-page"');
    expect(projectSettingsSource).not.toContain("member.email");
    expect(projectSettingsSource).not.toContain("member.company_roles");
    expect(styles).not.toContain(".ps-page");
    expect(styles).not.toContain(".ps-kpi-on");
    expect(styles).not.toContain(".ps-table");
  });
});
