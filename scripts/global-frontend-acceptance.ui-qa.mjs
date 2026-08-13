import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawn } from "node:child_process";
import { once } from "node:events";
import { createServer } from "node:net";
import { build } from "vite";
import {
  acceptanceViewports,
  buildRouteCoverage,
  explicitCaseResult,
  routeDefinitions,
} from "./global-frontend-acceptance.coverage.mjs";
import { waitForChildProcess } from "./ui-qa-process.mjs";

const configuredBase = process.env.UI_QA_BASE?.replace(/\/$/, "") || null;
let base = configuredBase || "";
const rootDir = path.resolve();
const outRoot = process.env.UI_QA_OUT_DIR || path.join(os.tmpdir(), "kap-ui-qa");
const outDir = path.join(outRoot, "global-frontend-acceptance");
const evidenceDir = path.join(outDir, "evidence");
const suiteTimeoutMs = Number(process.env.UI_QA_SUITE_TIMEOUT_MS || 90_000);
const suiteMaxAttempts = Number(process.env.UI_QA_SUITE_MAX_ATTEMPTS || 2);
const suiteConcurrency = Math.max(1, Number(process.env.UI_QA_SUITE_CONCURRENCY || 4));
if (path.basename(outDir) !== "global-frontend-acceptance") {
  throw new Error(`Refusing to reset unexpected UI QA output path: ${outDir}`);
}
fs.rmSync(outDir, { recursive: true, force: true });
fs.mkdirSync(evidenceDir, { recursive: true });

const suites = [
  {
    name: "project-settings",
    script: "project-settings.ui-qa.mjs",
    evidence: "project-settings",
  },
  {
    name: "knowledge-list",
    script: "knowledge-list.ui-qa.mjs",
    evidence: "knowledge-list",
  },
  {
    name: "knowledge-detail",
    script: "knowledge-detail.ui-qa.mjs",
    evidence: "knowledge-detail",
  },
  { name: "upload", script: "upload-ingest.ui-qa.mjs", evidence: "upload-ingest" },
  {
    name: "project-space",
    script: "project-space.ui-qa.mjs",
    evidence: "project-space",
  },
  {
    name: "project-knowledge",
    script: "project-knowledge.ui-qa.mjs",
    evidence: "project-knowledge",
  },
  {
    name: "review-access",
    script: "review-access.ui-qa.mjs",
    evidence: "review-access",
  },
  { name: "workbench", script: "workbench.ui-qa.mjs", evidence: "workbench" },
  {
    name: "personal-knowledge",
    script: "personal-knowledge.ui-qa.mjs",
    evidence: "personal-knowledge",
  },
  {
    name: "admin-ingest",
    script: "admin-operations.ui-qa.mjs",
    evidence: "admin-operations",
  },
  {
    name: "model-foundation",
    script: "model-foundation.ui-qa.mjs",
    evidence: "model-foundation",
  },
  {
    name: "wecom-scan",
    script: "wecom-scan.ui-qa.mjs",
    evidence: "wecom-scan",
  },
  {
    name: "security-operations",
    script: "security-operations.ui-qa.mjs",
    evidence: "security-operations",
  },
  {
    name: "people-permissions",
    script: "people-permissions.ui-qa.mjs",
    evidence: "people-permissions",
  },
  {
    name: "help-global",
    script: "help-global-experience.ui-qa.mjs",
    evidence: "help-global-experience",
  },
];

const selectedSuites = new Set(
  (process.env.UI_QA_SUITES || "")
    .split(",")
    .map((name) => name.trim())
    .filter(Boolean),
);
const suitesToRun = selectedSuites.size
  ? suites.filter((suite) => selectedSuites.has(suite.name))
  : suites;

let ownedServer = null;
let serverOutput = "";
let productionBuilt = false;

async function isServerReady() {
  if (!base) return false;
  try {
    const response = await fetch(base, { signal: AbortSignal.timeout(1000) });
    return response.ok;
  } catch {
    return false;
  }
}

function availablePort() {
  return new Promise((resolve, reject) => {
    const server = createServer();
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      const port = typeof address === "object" && address ? address.port : null;
      server.close((error) => {
        if (error) reject(error);
        else if (port) resolve(port);
        else reject(new Error("Unable to allocate a UI QA port."));
      });
    });
  });
}

async function ensureServer() {
  if (await isServerReady()) return;
  if (configuredBase) throw new Error(`UI_QA_BASE is not reachable: ${base}`);
  if (ownedServer?.exitCode === null) await stopOwnedServer();

  const port = await availablePort();
  base = `http://127.0.0.1:${port}`;

  if (!productionBuilt) {
    await build({ logLevel: "warn" });
    productionBuilt = true;
  }

  ownedServer = spawn(
    process.execPath,
    [
      path.join(rootDir, "node_modules/vite/bin/vite.js"),
      "preview",
      "--host",
      "127.0.0.1",
      "--port",
      String(port),
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
  const child = spawn(process.execPath, [path.join(rootDir, "scripts", suite.script)], {
    cwd: rootDir,
    env: { ...process.env, UI_QA_BASE: base, UI_QA_OUT_DIR: evidenceDir },
    stdio: ["ignore", "pipe", "pipe"],
    windowsHide: true,
  });
  return waitForChildProcess(child, {
    timeoutMs: suiteTimeoutMs,
    timeoutMessage: `UI QA suite timed out after ${suiteTimeoutMs}ms: ${suite.name}`,
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

async function executeSuite(suite) {
  console.log(`UI QA suite started: ${suite.name}`);
  const startedAt = Date.now();
  const suiteDir = path.join(evidenceDir, suite.evidence);
  let execution = null;
  const attemptFailures = [];
  for (let attempt = 1; attempt <= suiteMaxAttempts; attempt += 1) {
    fs.rmSync(suiteDir, { recursive: true, force: true });
    execution = await runSuite(suite);
    if (execution.code === 0) break;
    attemptFailures.push(`Attempt ${attempt}/${suiteMaxAttempts}\n${execution.output}`);
    if (attempt < suiteMaxAttempts) {
      console.warn(`UI QA suite retrying after failure: ${suite.name} (${attempt})`);
      await ensureServer();
    }
  }
  if (!execution) throw new Error(`UI QA suite did not execute: ${suite.name}`);
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
    timedOut: execution.timedOut,
    attempts: execution.code === 0 ? attemptFailures.length + 1 : suiteMaxAttempts,
    failureOutput: execution.code === 0 ? null : attemptFailures.join("\n\n"),
  });
  console.log(
    `UI QA suite ${execution.code === 0 ? "passed" : "failed"}: ${suite.name} (${Date.now() - startedAt}ms)`,
  );
}

async function runSuites() {
  let nextIndex = 0;
  const worker = async () => {
    while (nextIndex < suitesToRun.length) {
      const suite = suitesToRun[nextIndex];
      nextIndex += 1;
      await executeSuite(suite);
    }
  };
  const workerCount = Math.min(suiteConcurrency, suitesToRun.length);
  await Promise.all(Array.from({ length: workerCount }, () => worker()));
}

try {
  await ensureServer();
  await runSuites();
} finally {
  await stopOwnedServer();
}

const routeCoverage = buildRouteCoverage(routeDefinitions, suiteResults);
const failedSuites = suiteResults.filter((suite) => suite.status === "failed");
const skippedRoutes = routeCoverage.filter((route) => route.status === "skipped");
const passedRoutes = routeCoverage.filter((route) => route.status === "passed");
const allScreenshots = [...new Set(suiteResults.flatMap((suite) => suite.screenshots))];
const viewportEvidence = Object.fromEntries(
  acceptanceViewports.map((viewport) => [
    viewport,
    allScreenshots.filter((file) => file.endsWith(`-${viewport}.png`)),
  ]),
);
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
    viewportScreenshots: Object.fromEntries(
      Object.entries(viewportEvidence).map(([viewport, files]) => [viewport, files.length]),
    ),
  },
  routeCoverage,
  suites: suiteResults,
  screenshots: allScreenshots,
  viewportEvidence,
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
