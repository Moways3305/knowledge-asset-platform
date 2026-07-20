import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawn } from "node:child_process";
import { once } from "node:events";
import {
  buildRouteCoverage,
  explicitCaseResult,
  routeDefinitions,
} from "./pbc91_global_frontend_acceptance_coverage.mjs";

const base = (process.env.UI_QA_BASE || "http://127.0.0.1:5179").replace(/\/$/, "");
const rootDir = path.resolve();
const outRoot = process.env.UI_QA_OUT_DIR || path.join(os.tmpdir(), "kap-ui-qa");
const outDir = path.join(outRoot, "pbc91-global-acceptance");
const evidenceDir = path.join(outDir, "evidence");
if (path.basename(outDir) !== "pbc91-global-acceptance") {
  throw new Error(`Refusing to reset unexpected UI QA output path: ${outDir}`);
}
fs.rmSync(outDir, { recursive: true, force: true });
fs.mkdirSync(evidenceDir, { recursive: true });

const suites = [
  {
    name: "project-settings",
    script: "pbc74_project_settings_ui_qa.mjs",
    evidence: "pbc74-project-settings",
  },
  {
    name: "knowledge-list",
    script: "pbc75_knowledge_list_ui_qa.mjs",
    evidence: "pbc75-knowledge-list",
  },
  {
    name: "knowledge-detail",
    script: "pbc76_knowledge_detail_ui_qa.mjs",
    evidence: "pbc76-knowledge-detail",
  },
  { name: "upload", script: "pbc77_upload_ingest_ui_qa.mjs", evidence: "pbc77-upload-ingest" },
  {
    name: "project-space",
    script: "pbc78_project_space_ui_qa.mjs",
    evidence: "pbc78-project-space",
  },
  {
    name: "project-knowledge",
    script: "pbc79_project_knowledge_ui_qa.mjs",
    evidence: "pbc79-project-knowledge",
  },
  {
    name: "review-access",
    script: "pbc80_review_access_ui_qa.mjs",
    evidence: "pbc80-review-access",
  },
  { name: "workbench", script: "pbc81_workbench_ui_qa.mjs", evidence: "pbc81-workbench" },
  {
    name: "personal-knowledge",
    script: "pbc83_personal_knowledge_ui_qa.mjs",
    evidence: "pbc83-personal-knowledge",
  },
  {
    name: "admin-ingest",
    script: "pbc85_admin_operations_closure_ui_qa.mjs",
    evidence: "pbc85-admin-operations-closure",
  },
  {
    name: "model-foundation",
    script: "pbc86_model_foundation_ui_qa.mjs",
    evidence: "pbc86-model-foundation",
  },
  {
    name: "wecom-scan",
    script: "pbc87_wecom_scan_ui_qa.mjs",
    evidence: "pbc87-wecom-scan",
  },
  {
    name: "security-operations",
    script: "pbc88_audit_security_operations_ui_qa.mjs",
    evidence: "pbc88-security-operations",
  },
  {
    name: "people-permissions",
    script: "pbc89_people_permissions_ui_qa.mjs",
    evidence: "pbc89-people-permissions",
  },
  {
    name: "help-global",
    script: "pbc90_help_global_experience_ui_qa.mjs",
    evidence: "pbc90-help-global",
  },
];

let ownedServer = null;
let serverOutput = "";

async function isServerReady() {
  try {
    const response = await fetch(base, { signal: AbortSignal.timeout(1000) });
    return response.ok;
  } catch {
    return false;
  }
}

async function ensureServer() {
  if (await isServerReady()) return;
  if (process.env.UI_QA_BASE) throw new Error(`UI_QA_BASE is not reachable: ${base}`);

  ownedServer = spawn(
    process.execPath,
    [
      path.join(rootDir, "node_modules/vite/bin/vite.js"),
      "--host",
      "127.0.0.1",
      "--port",
      "5179",
      "--strictPort",
    ],
    { cwd: rootDir, stdio: ["ignore", "pipe", "pipe"], windowsHide: true },
  );
  const collect = (chunk) => {
    serverOutput = `${serverOutput}${chunk.toString()}`.slice(-4000);
  };
  ownedServer.stdout.on("data", collect);
  ownedServer.stderr.on("data", collect);

  for (let attempt = 0; attempt < 80; attempt += 1) {
    if (await isServerReady()) return;
    if (ownedServer.exitCode !== null) throw new Error(`QA server exited early.\n${serverOutput}`);
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  throw new Error(`QA server did not become ready.\n${serverOutput}`);
}

async function stopOwnedServer() {
  if (!ownedServer || ownedServer.exitCode !== null) return;
  ownedServer.kill();
  await Promise.race([
    once(ownedServer, "exit"),
    new Promise((resolve) => setTimeout(resolve, 1500)),
  ]);
  if (ownedServer.exitCode === null) ownedServer.kill("SIGKILL");
}

function runSuite(suite) {
  return new Promise((resolve) => {
    const child = spawn(process.execPath, [path.join(rootDir, "scripts", suite.script)], {
      cwd: rootDir,
      env: { ...process.env, UI_QA_BASE: base, UI_QA_OUT_DIR: evidenceDir },
      stdio: ["ignore", "pipe", "pipe"],
      windowsHide: true,
    });
    let output = "";
    const collect = (chunk) => {
      output = `${output}${chunk.toString()}`.slice(-8000);
    };
    child.stdout.on("data", collect);
    child.stderr.on("data", collect);
    child.on("close", (code) => resolve({ code: code ?? 1, output }));
  });
}

function filesRecursively(directory, extension) {
  if (!fs.existsSync(directory)) return [];
  return fs.readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const entryPath = path.join(directory, entry.name);
    return entry.isDirectory()
      ? filesRecursively(entryPath, extension)
      : entry.name.endsWith(extension)
        ? [entryPath]
        : [];
  });
}

const suiteResults = [];

try {
  await ensureServer();
  for (const suite of suites) {
    const startedAt = Date.now();
    const execution = await runSuite(suite);
    const suiteDir = path.join(evidenceDir, suite.evidence);
    const reportPath = path.join(suiteDir, "report.json");
    let cases = [];
    if (fs.existsSync(reportPath)) {
      const parsed = JSON.parse(fs.readFileSync(reportPath, "utf8"));
      cases = Array.isArray(parsed) ? parsed : parsed.results || [];
    }
    const screenshots = filesRecursively(suiteDir, ".png").map((file) => path.resolve(file));
    const explicitPassed = cases.filter((item) => explicitCaseResult(item) === true).length;
    const explicitFailed = cases.filter((item) => explicitCaseResult(item) === false).length;
    const hasExplicitCaseStatus = explicitPassed + explicitFailed > 0;
    suiteResults.push({
      name: suite.name,
      script: suite.script,
      status: execution.code === 0 ? "passed" : "failed",
      caseCount: cases.length,
      passedCount:
        execution.code === 0
          ? cases.length - explicitFailed
          : hasExplicitCaseStatus
            ? explicitPassed
            : 0,
      failedCount:
        execution.code === 0
          ? explicitFailed
          : hasExplicitCaseStatus
            ? explicitFailed || 1
            : cases.length || 1,
      durationMs: Date.now() - startedAt,
      reportPath: fs.existsSync(reportPath) ? path.resolve(reportPath) : null,
      cases,
      screenshots,
      failureOutput: execution.code === 0 ? null : execution.output,
    });
  }
} finally {
  await stopOwnedServer();
}

const routeCoverage = buildRouteCoverage(routeDefinitions, suiteResults);
const failedSuites = suiteResults.filter((suite) => suite.status === "failed");
const skippedRoutes = routeCoverage.filter((route) => route.status === "skipped");
const passedRoutes = routeCoverage.filter((route) => route.status === "passed");
const allScreenshots = [...new Set(suiteResults.flatMap((suite) => suite.screenshots))];
const acceptanceChecks = routeCoverage.flatMap((route) =>
  route.checks.map((check) => ({ route: route.route, ...check })),
);
const report = {
  generatedAt: new Date().toISOString(),
  base,
  summary: {
    suites: suiteResults.length,
    totalRoutes: routeCoverage.length,
    passedRoutes: passedRoutes.length,
    skippedRoutes: skippedRoutes.length,
    failedRoutes: routeCoverage.length - passedRoutes.length - skippedRoutes.length,
    totalAcceptanceChecks: acceptanceChecks.length,
    passedAcceptanceChecks: acceptanceChecks.filter((check) => check.status === "passed").length,
    skippedAcceptanceChecks: acceptanceChecks.filter((check) => check.status === "skipped").length,
    failedAcceptanceChecks: acceptanceChecks.filter((check) => check.status === "failed").length,
    totalCases: suiteResults.reduce((sum, suite) => sum + suite.caseCount, 0),
    passedCases: suiteResults.reduce((sum, suite) => sum + suite.passedCount, 0),
    failedCases: suiteResults.reduce((sum, suite) => sum + suite.failedCount, 0),
    screenshots: allScreenshots.length,
  },
  routeCoverage,
  suites: suiteResults,
  screenshots: allScreenshots,
};
const reportPath = path.join(outDir, "report.json");
fs.writeFileSync(reportPath, JSON.stringify(report, null, 2));
console.log(
  JSON.stringify({ reportPath: path.resolve(reportPath), summary: report.summary }, null, 2),
);

const failedAcceptanceChecks = acceptanceChecks.filter((check) => check.status !== "passed");
if (failedAcceptanceChecks.length > 0) {
  console.error(JSON.stringify({ failedAcceptanceChecks }, null, 2));
}

if (
  failedSuites.length > 0 ||
  passedRoutes.length !== routeCoverage.length ||
  failedAcceptanceChecks.length > 0
)
  process.exitCode = 1;
