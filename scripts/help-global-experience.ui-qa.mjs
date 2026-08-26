import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawn } from "node:child_process";
import { once } from "node:events";
import { chromium } from "playwright";

const base = (process.env.UI_QA_BASE || "http://127.0.0.1:5179").replace(/\/$/, "");
const outRoot = process.env.UI_QA_OUT_DIR || path.join(os.tmpdir(), "kap-ui-qa");
const outDir = path.join(outRoot, "help-global-experience");
fs.mkdirSync(outDir, { recursive: true });

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
  if (process.env.UI_QA_BASE) {
    throw new Error(`UI_QA_BASE is not reachable: ${base}`);
  }

  const viteEntry = path.resolve("node_modules/vite/bin/vite.js");
  ownedServer = spawn(
    process.execPath,
    [viteEntry, "--host", "127.0.0.1", "--port", "5179", "--strictPort"],
    { cwd: process.cwd(), stdio: ["ignore", "pipe", "pipe"], windowsHide: true },
  );
  const collectOutput = (chunk) => {
    serverOutput = `${serverOutput}${chunk.toString()}`.slice(-4000);
  };
  ownedServer.stdout.on("data", collectOutput);
  ownedServer.stderr.on("data", collectOutput);

  for (let attempt = 0; attempt < 80; attempt += 1) {
    if (await isServerReady()) return;
    if (ownedServer.exitCode !== null) {
      throw new Error(`PBC-90 UI QA server exited early.\n${serverOutput}`);
    }
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  throw new Error(`PBC-90 UI QA server did not become ready.\n${serverOutput}`);
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

const scenarios = ["help", "not-found", "loading", "forbidden", "error", "empty"];
const viewports = [
  { name: "1440", width: 1440, height: 1000 },
  { name: "1024", width: 1024, height: 900 },
  { name: "390", width: 390, height: 844 },
];
const workbenchOverview = {
  task_center: {
    status: "empty",
    error_code: null,
    summary: { needs_action: 0, running: 0, attention: 0, completed_today: 0 },
    priority_items: [],
    my_tasks: [],
    running_jobs: [],
    attention_items: [],
    recent_completed: [],
  },
  todos: { status: "empty", error_code: null, items: [], total: 0 },
  operations: { status: "empty", error_code: null, data: null },
  projects: { status: "empty", error_code: null, items: [], total: 0 },
  recent_activity: { status: "empty", error_code: null, items: [], total: 0 },
};
let browser;

try {
  await ensureServer();
  browser = await chromium.launch({ args: ["--disable-gpu"] });
  const results = [];

  for (const scenario of scenarios) {
    for (const viewport of viewports) {
      const context = await browser.newContext({ viewport });
      await context.route("**/api/v1/**", async (route) => {
        const requestUrl = new URL(route.request().url());
        const fulfill = (body, status = 200) =>
          route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

        if (requestUrl.pathname === "/api/v1/auth/me") {
          const pureAdmin = scenario === "forbidden";
          return fulfill({
            user_id: "00000000-0000-0000-0000-000000000090",
            name: pureAdmin ? "系统管理员验收用户" : "帮助体验验收用户",
            email: "identity-must-not-render@example.test",
            status: "active",
            company_roles: pureAdmin ? ["admin"] : ["consultant"],
            active_company_role: pureAdmin ? "admin" : "consultant",
            is_business_user: !pureAdmin,
            can_discover_l5: false,
            project_memberships: [],
          });
        }

        if (requestUrl.pathname === "/api/v1/workbench/overview") {
          return fulfill(workbenchOverview);
        }

        if (requestUrl.pathname === "/api/v1/notifications") {
          return fulfill({
            items: [],
            total: 0,
            page: 1,
            page_size: 20,
            unread_count: 0,
            categories: [],
          });
        }

        if (requestUrl.pathname === "/api/v1/knowledge/directories") {
          if (requestUrl.searchParams.get("scope") === "company") {
            return fulfill({
              items: [
                {
                  directory_key: "company.methodology",
                  name: "方法论",
                  description: "UI QA governed directory",
                  scope: "company",
                  project_id: null,
                },
              ],
            });
          }
          return fulfill({ items: [] });
        }

        if (requestUrl.pathname === "/api/v1/knowledge") {
          if (scenario === "loading") {
            await new Promise((resolve) => setTimeout(resolve, 8000));
            return fulfill({ items: [], total: 0, page: 1, page_size: 20, has_next: false });
          }
          if (scenario === "error") {
            return fulfill(
              { detail: { message: "SECRET-LIKE upstream body /internal/knowledge token=unsafe" } },
              503,
            );
          }
          return fulfill({ items: [], total: 0, page: 1, page_size: 20, has_next: false });
        }

        return fulfill({ detail: { message: "UI QA route not configured" } }, 404);
      });

      const page = await context.newPage();
      const consoleErrors = [];
      page.on("console", (message) => {
        if (message.type() === "error" && !message.text().startsWith("Failed to load resource:")) {
          consoleErrors.push(message.text());
        }
      });

      const target =
        scenario === "help"
          ? "/help"
          : scenario === "not-found"
            ? "/missing-pbc90"
            : ["loading", "error", "empty"].includes(scenario)
              ? "/knowledge?scope=company&directory_key=company.methodology"
              : "/knowledge";
      await page.goto(`${base}${target}`, {
        waitUntil: scenario === "loading" ? "domcontentloaded" : "networkidle",
      });

      if (scenario === "help") {
        await page.getByRole("heading", { name: "帮助中心" }).waitFor();
        await page.getByLabel("定位章节").selectOption("review");
        await page.getByRole("link", { name: "跳转到章节" }).click();
        await page.waitForFunction(() => window.location.hash === "#review");
        await page.evaluate(() => {
          window.scrollTo(0, 0);
          document.querySelector(".app-content")?.scrollTo(0, 0);
        });
      } else if (scenario === "not-found") {
        await page.getByRole("heading", { name: "页面不存在或已不可用" }).waitFor();
      } else if (scenario === "loading") {
        await page.locator(".product-state-shell.is-loading").waitFor();
      } else if (scenario === "forbidden") {
        await page.getByText("当前账号无此入口").waitFor();
      } else if (scenario === "error") {
        await page.getByText("知识资产加载失败").waitFor();
      } else {
        await page.getByText("暂无可复用资料").waitFor();
      }

      await page.waitForTimeout(160);
      const metrics = await page.evaluate((currentScenario) => {
        const root = document.documentElement;
        const directory = document.querySelector(".help-directory")?.getBoundingClientRect();
        const content = document.querySelector(".help-content")?.getBoundingClientRect();
        const state = document
          .querySelector(
            ".global-state-page, .product-state-shell, .state-box, .product-empty-state, .product-table-state-content",
          )
          ?.getBoundingClientRect();
        const bodyText = document.body.innerText;
        const clippedActions = [...document.querySelectorAll("button, a")].filter((element) => {
          const rect = element.getBoundingClientRect();
          return (
            rect.width > 0 &&
            (element.scrollWidth > element.clientWidth + 2 || rect.right > innerWidth + 2)
          );
        }).length;
        return {
          scenario: currentScenario,
          overflowX: root.scrollWidth - root.clientWidth,
          clippedActions,
          sensitiveTextVisible:
            /SECRET-LIKE|upstream body|\/internal\/knowledge|token=unsafe|identity-must-not-render/i.test(
              bodyText,
            ),
          helpDirectoryWidth: directory?.width ?? 0,
          helpContentRatio: directory && content ? content.width / directory.width : 0,
          helpSections: document.querySelectorAll(".help-section").length,
          helpIcons: document.querySelectorAll(".help-section-icon svg").length,
          jumpWorked: currentScenario !== "help" || window.location.hash === "#review",
          stateHeight: state?.height ?? 0,
          stateGraphic: Boolean(
            document.querySelector(
              ".global-state-graphic svg, .product-state-icon svg, .product-empty-icon svg, .product-table-state-content svg, .state-box svg",
            ),
          ),
          stateActions: document.querySelectorAll(
            ".global-state-actions button, .global-state-actions a, .product-state-shell button, .product-state-actions a, .product-empty-actions button",
          ).length,
          reachableActions: document.querySelectorAll(
            ".global-state-actions button, .global-state-actions a, .product-state-shell button, .product-state-actions a, .product-empty-actions button, .product-page-actions a, .product-page-actions button",
          ).length,
        };
      }, scenario);

      await page.screenshot({
        path: path.join(outDir, `${scenario}-${viewport.name}.png`),
        fullPage: false,
        animations: "disabled",
      });
      results.push({ viewport: viewport.name, consoleErrors, ...metrics });
      await context.close();
    }
  }

  await browser.close();
  browser = null;
  fs.writeFileSync(path.join(outDir, "report.json"), JSON.stringify(results, null, 2));
  console.log(JSON.stringify({ outDir, results }, null, 2));

  const failed = results.some((result) => {
    const baseFailure =
      result.overflowX > 2 ||
      result.clippedActions > 0 ||
      result.sensitiveTextVisible ||
      result.consoleErrors.length > 0;
    if (result.scenario === "help") {
      const desktop = result.viewport === "1440";
      return (
        baseFailure ||
        (desktop && (result.helpDirectoryWidth < 220 || result.helpDirectoryWidth > 250)) ||
        (desktop && result.helpContentRatio < 2.4) ||
        (!desktop && result.helpDirectoryWidth <= 0) ||
        result.helpSections !== 12 ||
        result.helpIcons !== 12 ||
        !result.jumpWorked
      );
    }
    if (result.scenario === "not-found") {
      return (
        baseFailure || !result.stateGraphic || result.stateHeight > 420 || result.stateActions !== 2
      );
    }
    if (result.scenario === "loading") {
      return (
        baseFailure || !result.stateGraphic || result.stateHeight > 260 || result.stateActions !== 0
      );
    }
    return (
      baseFailure || !result.stateGraphic || result.stateHeight > 420 || result.reachableActions < 1
    );
  });

  if (failed) process.exitCode = 1;
} finally {
  await browser?.close();
  await stopOwnedServer();
}
