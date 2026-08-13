import path from "node:path";

export const acceptanceViewports = ["1440", "1024", "390"];

export const routeDefinitions = [
  {
    route: "/",
    suite: "workbench",
    states: [
      { name: "normal", scenario: "normal" },
      { name: "empty", scenario: "projects-empty" },
      { name: "failure", scenario: "recent-error-retry" },
      { name: "forbidden", scenario: "projects-forbidden" },
    ],
  },
  {
    route: "/knowledge",
    suite: "knowledge-list",
    states: [
      { name: "normal", scenario: "company" },
      { name: "project", scenario: "project" },
      { name: "empty", scenario: "empty" },
      { name: "failure", scenario: "retry" },
      { name: "forbidden", scenario: "pure-admin" },
    ],
  },
  {
    route: "/knowledge/:id",
    suite: "knowledge-detail",
    states: [
      { name: "normal", scenario: "full" },
      { name: "restricted", scenario: "restricted" },
      { name: "failure", scenario: "failure" },
      { name: "denied", scenario: "denied" },
    ],
  },
  {
    route: "/my/knowledge",
    suite: "personal-knowledge",
    states: [
      { name: "normal", scenario: "default" },
      { name: "empty", scenario: "empty" },
      { name: "failure", scenario: "list-error" },
      { name: "forbidden", scenario: "forbidden" },
    ],
  },
  {
    route: "/upload",
    suite: "upload",
    states: [
      { name: "normal", scenario: "local-queue" },
      { name: "empty", scenario: "wecom-empty" },
      { name: "failure", scenario: "local-upload-failure-retry" },
    ],
  },
  {
    route: "/admin/ingest",
    suite: "admin-ingest",
    states: [
      { name: "normal", scenario: "normal-trend" },
      { name: "empty", scenario: "empty" },
      { name: "failure", scenario: "health-error" },
      { name: "forbidden", scenario: "forbidden" },
    ],
  },
  {
    route: "/admin/wecom-scan",
    suite: "wecom-scan",
    states: [
      { name: "normal", scenario: "normal" },
      { name: "empty", scenario: "empty" },
      { name: "action-failure", scenario: "scan-failure" },
      { name: "forbidden", scenario: "forbidden" },
    ],
  },
  {
    route: "/admin/weknora-models",
    suite: "model-foundation",
    states: [
      { name: "normal", scenario: "normal" },
      { name: "empty", scenario: "empty" },
      { name: "configuration", scenario: "external-drawer" },
      { name: "forbidden", scenario: "forbidden" },
    ],
  },
  ...[
    ["/admin/audit", "audit"],
    ["/admin/auth-security", "auth"],
    ["/admin/alert-settings", "alerts"],
  ].map(([route, page]) => ({
    route,
    suite: "security-operations",
    states: ["normal", "empty", "failure", "forbidden"].map((name) => ({
      name,
      scenario: name,
      page,
    })),
  })),
  ...[
    ["/admin/people", "people"],
    ["/admin/permissions", "permissions"],
  ].map(([route, page]) => ({
    route,
    suite: "people-permissions",
    states: ["normal", "empty", "failure", "forbidden"].map((name) => ({
      name,
      scenario: name,
      page,
    })),
  })),
  {
    route: "/admin/company-kb",
    suite: "people-permissions",
    states: [{ name: "empty", scenario: "normal", page: "company-kb" }],
  },
  {
    route: "/review",
    suite: "review-access",
    states: ["normal", "loading", "empty", "list-failure", "forbidden"].map((name) => ({
      name: name === "list-failure" ? "failure" : name,
      scenario: `review-${name}`,
    })),
  },
  {
    route: "/original-access",
    suite: "review-access",
    states: ["inbox", "loading", "empty", "list-failure", "forbidden"].map((name) => ({
      name: name === "inbox" ? "normal" : name === "list-failure" ? "failure" : name,
      scenario: `access-${name}`,
    })),
  },
  {
    route: "/project/:id",
    suite: "project-space",
    states: [
      { name: "normal", scenario: "manager" },
      { name: "empty", scenario: "empty-projects" },
      { name: "failure", scenario: "overview-failure" },
      { name: "forbidden", scenario: "inaccessible" },
    ],
  },
  {
    route: "/project/:id/knowledge",
    suite: "project-knowledge",
    states: [
      { name: "normal", scenario: "member-list" },
      { name: "empty", scenario: "filtered-empty" },
      { name: "failure", scenario: "list-failure" },
      { name: "forbidden", scenario: "inaccessible" },
    ],
  },
  {
    route: "/project/:id/settings",
    suite: "project-settings",
    states: [
      { name: "normal", scenario: "manager-pending" },
      { name: "empty", scenario: "manager-empty" },
      { name: "failure", scenario: "review-error" },
      { name: "readonly", scenario: "member-readonly" },
      { name: "delete-ready", scenario: "delete-ready" },
      { name: "delete-blocked", scenario: "delete-blocked" },
      { name: "delete-forbidden", scenario: "delete-unauthorized" },
    ],
  },
  {
    route: "/help",
    suite: "help-global",
    states: [{ name: "normal", scenario: "help" }],
  },
  {
    route: "*",
    suite: "help-global",
    states: [{ name: "not-found", scenario: "not-found" }],
  },
];

function matchingScreenshot(screenshots, state, viewport) {
  const baseName = `${state.page ? `${state.page}-` : ""}${state.scenario}-${viewport}.png`;
  return (
    screenshots.find((screenshot) => path.basename(screenshot.replace(/\\/g, "/")) === baseName) ||
    null
  );
}

export function explicitCaseResult(item) {
  if (item.passed === false || item.pass === false) return false;
  if (item.passed === true || item.pass === true) return true;
  return null;
}

export function buildRouteCoverage(definitions, suiteResults) {
  return definitions.map((definition) => {
    const suite = suiteResults.find((item) => item.name === definition.suite);
    const checks = definition.states.flatMap((state) =>
      acceptanceViewports.map((viewport) => {
        const matches = (suite?.cases || []).filter(
          (item) =>
            item.scenario === state.scenario &&
            String(item.viewport) === viewport &&
            (state.page === undefined || item.page === state.page),
        );
        const evidence = matchingScreenshot(suite?.screenshots || [], state, viewport);
        let reason = null;
        if (!suite) reason = "missing-suite";
        else if (suite.status !== "passed") reason = "suite-failed";
        else if (matches.length === 0) reason = "missing-case";
        else if (matches.length > 1) reason = "ambiguous-case";
        else if (explicitCaseResult(matches[0]) === false) reason = "case-failed";
        else if (!evidence) reason = "missing-screenshot";

        return {
          state: state.name,
          scenario: state.scenario,
          ...(state.page ? { page: state.page } : {}),
          viewport,
          status: reason ? "failed" : "passed",
          reason,
          evidence,
        };
      }),
    );
    return {
      route: definition.route,
      suite: definition.suite,
      states: definition.states.map((state) => state.name),
      viewports: acceptanceViewports,
      status: checks.every((check) => check.status === "passed") ? "passed" : "failed",
      checks,
    };
  });
}
