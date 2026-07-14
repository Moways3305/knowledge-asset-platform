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
    owners: ["pages/HomeDashboardPage.tsx"],
    apiModules: ["http", "ingest", "knowledge", "project", "review"],
  },
  {
    route: "/knowledge",
    component: "KnowledgeListPage",
    guard: "viewKnowledge",
    owners: ["pages/KnowledgeListPage.tsx", "pages/knowledge/CreateProjectModal.tsx"],
    apiModules: ["admin", "auth", "http", "knowledge", "project"],
  },
  {
    route: "/knowledge/:id",
    component: "KnowledgeDetailPage",
    guard: "viewKnowledge",
    owners: ["pages/KnowledgeDetailPage.tsx"],
    apiModules: ["http", "knowledge"],
    allowedTimerOwners: ["pages/KnowledgeDetailPage.tsx"],
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
    apiModules: ["auth", "http", "personal", "weknoraModels", "workbuddy"],
  },
  {
    route: "/upload",
    component: "UploadPage",
    guard: "viewUpload",
    owners: ["pages/upload/useUploadFlow.ts", "hooks/useModelSelection.ts"],
    apiModules: ["auth", "http", "ingest", "weknoraModels"],
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
    owners: [
      "pages/AdminWecomScanPage.tsx",
      "pages/wecomScan/WecomDirectoryPicker.tsx",
      "pages/wecomScan/WecomScanConfigForm.tsx",
    ],
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
    apiModules: ["review"],
  },
  {
    route: "/original-access",
    component: "OriginalAccessPage",
    guard: "viewOriginalAccess",
    owners: ["pages/OriginalAccessPage.tsx"],
    apiModules: ["http", "knowledge"],
  },
  {
    route: "/project/:id/knowledge",
    component: "ProjectKnowledgePage",
    guard: "viewProject",
    owners: ["pages/ProjectKnowledgePage.tsx"],
    apiModules: ["http", "knowledge", "project"],
  },
  {
    route: "/project/:id/settings",
    component: "ProjectSettingsPage",
    guard: "viewProject",
    owners: ["pages/ProjectSettingsPage.tsx"],
    apiModules: ["auth", "http", "project"],
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

const sourceModules = import.meta.glob(
  ["../App.tsx", "../{pages,components,hooks}/**/*.{ts,tsx}"],
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

describe("frontend route takeover gate", () => {
  it("assigns every formal App route to the registered page and capability", () => {
    const actual = appRouteOwnership();
    expect(actual.size).toBe(18);
    expect([...actual.keys()].sort()).toEqual(routes.map((item) => item.route).sort());
    for (const contract of routes) {
      expect(actual.get(contract.route), contract.route).toEqual({
        component: contract.component,
        guard: contract.guard,
      });
    }
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
});
