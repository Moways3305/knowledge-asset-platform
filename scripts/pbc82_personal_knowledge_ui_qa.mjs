import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { chromium } from "playwright";
import { build, preview } from "vite";

const port = Number(process.env.UI_QA_PORT || 5197);
const base = `http://127.0.0.1:${port}`;
const outRoot = process.env.UI_QA_OUT_DIR || path.join(os.tmpdir(), "kap-ui-qa");
const outDir = path.join(outRoot, "pbc82-personal-knowledge");
fs.mkdirSync(outDir, { recursive: true });

const viewports = [
  { name: "1440", width: 1440, height: 1000 },
  { name: "1920", width: 1920, height: 1080 },
];
const scenarios = ["normal", "no-kb", "empty", "no-project", "forbidden", "list-error", "write-error"];

const authMe = {
  user_id: "00000000-0000-0000-0000-000000000082",
  name: "个人知识验收用户",
  email: "personal-qa@example.test",
  status: "active",
  company_roles: ["consultant"],
  is_business_user: true,
  can_discover_l5: false,
  project_memberships: [
    {
      project_id: "00000000-0000-0000-0000-0000000000a2",
      project_name: "企业知识治理项目",
      project_role: "consultant",
      status: "active",
    },
  ],
};

const accessInfo = {
  discovery: true,
  summary: true,
  original: true,
  effective_source: "owner",
  can_request_original: false,
  existing_request_status: null,
  existing_grant_expires_at: null,
  can_delete: true,
  can_manage_lifecycle: true,
};

const items = [
  {
    id: "00000000-0000-0000-0000-0000000000d2",
    title: "客户访谈洞察整理",
    scope: "personal",
    zone: "material",
    asset_type: "insight",
    confidentiality_level: "L2",
    ai_access_level: "A2",
    asset_status: "active",
    visibility: "confidential",
    tags: [],
    summary_text: "secret summary must not render",
    project_name: null,
    lifecycle_phase: null,
    confidence: null,
    last_called_at: null,
    updated_at: "2026-07-17T02:30:00Z",
    access_info: accessInfo,
  },
  {
    id: "00000000-0000-0000-0000-0000000000e2",
    title: "项目复盘方法模板",
    scope: "personal",
    zone: "asset",
    asset_type: "template",
    confidentiality_level: "L2",
    ai_access_level: "A2",
    asset_status: "active",
    visibility: "confidential",
    tags: [],
    summary_text: null,
    project_name: null,
    lifecycle_phase: null,
    confidence: null,
    last_called_at: null,
    updated_at: "2026-07-16T07:20:00Z",
    access_info: accessInfo,
  },
];

let server;
let browser;
const results = [];

try {
  await build({ logLevel: "warn" });
  server = await preview({ preview: { host: "127.0.0.1", port, strictPort: true }, logLevel: "warn" });
  browser = await chromium.launch({ args: ["--disable-gpu"] });

  for (const scenario of scenarios) {
    for (const viewport of viewports) {
      const context = await browser.newContext({ viewport });
      const browserMessages = [];
      let unexpectedCalls = 0;
      await context.route("**/api/v1/**", async (route) => {
        const url = new URL(route.request().url());
        const method = route.request().method();
        const fulfill = (body, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

        if (url.pathname === "/api/v1/auth/me") {
          return fulfill({ ...authMe, project_memberships: scenario === "no-project" ? [] : authMe.project_memberships });
        }
        if (url.pathname === "/api/v1/auth/csrf") return fulfill({ csrf_token: "csrf-safe-82" });
        if (url.pathname === "/api/v1/weknora/model-options") return fulfill({ items: [], default_missing: false });
        if (url.pathname === "/api/v1/my/knowledge" && method === "GET") {
          if (scenario === "forbidden") return fulfill({ detail: "secret_denied_reason" }, 403);
          if (scenario === "list-error") return fulfill({ detail: "SECRET-LIKE upstream" }, 500);
          return fulfill({ items: scenario === "empty" ? [] : items, total: scenario === "empty" ? 0 : items.length });
        }
        if (url.pathname === "/api/v1/my/knowledge-base" && method === "GET") {
          if (scenario === "forbidden") return fulfill({ detail: "secret_denied_reason" }, 403);
          return fulfill(scenario === "no-kb" ? { exists: false } : {
            exists: true,
            display_name: "个人方法知识库",
            status: "active",
            knowledge_count: 2,
            embedding_model_ref: "secret-model-ref-82",
          });
        }
        if (url.pathname === "/api/v1/my/knowledge-base" && method === "POST") {
          return fulfill({ exists: true, display_name: "我的知识库", status: "active" });
        }
        if (url.pathname === "/api/v1/my/knowledge-base" && method === "PUT") {
          return fulfill({ exists: true, display_name: "更新后的名称", status: "active" });
        }
        if (url.pathname.endsWith("/confirm-asset") && method === "POST") {
          if (scenario === "write-error") return fulfill({ detail: "SECRET-LIKE write failure" }, 500);
          return fulfill({ asset_id: "safe", zone: "asset", status: "active", message: "secret server copy" });
        }
        if (url.pathname.endsWith("/submit-to-project") && method === "POST") {
          return fulfill({ message: "已正式入库" });
        }
        if (url.pathname.endsWith("/validation-evidence") && method === "POST") {
          return fulfill({ message: "客户已验证" });
        }
        unexpectedCalls += 1;
        return fulfill({ detail: "unexpected endpoint" }, 500);
      });

      const page = await context.newPage();
      page.on("console", (message) => browserMessages.push(message.text()));
      page.on("pageerror", (error) => browserMessages.push(error.message));
      await page.goto(`${base}/my/knowledge`, { waitUntil: "networkidle" });
      await page.getByRole("heading", { name: "我的个人知识" }).waitFor();

      if (scenario === "no-kb") {
        await page.getByRole("button", { name: "创建知识库" }).click();
        await page.getByRole("dialog").waitFor();
      } else if (scenario === "normal") {
        await page.screenshot({ path: path.join(outDir, `normal-base-${viewport.name}.png`), animations: "disabled" });
        await page.getByRole("button", { name: "修改名称" }).click();
        await page.screenshot({ path: path.join(outDir, `rename-dialog-${viewport.name}.png`), animations: "disabled" });
        await page.getByRole("dialog").getByRole("button", { name: "取消" }).click();
        await page.getByRole("button", { name: "本人确认" }).click();
        await page.screenshot({ path: path.join(outDir, `confirm-dialog-${viewport.name}.png`), animations: "disabled" });
        await page.getByRole("dialog").getByRole("button", { name: "取消" }).click();
        await page.getByRole("button", { name: "提交项目" }).click();
        await page.screenshot({ path: path.join(outDir, `submit-dialog-${viewport.name}.png`), animations: "disabled" });
        await page.getByRole("dialog").getByRole("button", { name: "取消" }).click();
        await page.getByRole("link", { name: "项目复盘方法模板" }).locator("xpath=ancestor::tr").getByRole("button", { name: "登记证据" }).click();
        await page.getByRole("dialog").waitFor();
        await page.screenshot({ path: path.join(outDir, `evidence-dialog-${viewport.name}.png`), animations: "disabled" });
      } else if (scenario === "write-error") {
        await page.getByRole("button", { name: "本人确认" }).click();
        await page.getByRole("dialog").getByRole("button", { name: "确认资产" }).click();
        await page.getByText("确认失败，请稍后重试").waitFor();
      }

      const result = await page.evaluate((scenarioName) => {
        const text = document.body.innerText;
        const root = document.documentElement;
        const shell = document.querySelector(".rail")?.getBoundingClientRect();
        const content = document.querySelector(".app-content")?.getBoundingClientRect();
        const table = document.querySelector(".mk82-table")?.getBoundingClientRect();
        const stats = [...document.querySelectorAll(".mk82-stats article")].map((node) => node.getBoundingClientRect());
        const forbidden = ["secret-model-ref-82", "secret_denied_reason", "SECRET-LIKE", "secret server copy", "已正式入库", "客户已验证", "storage_ref", "weknora"];
        return {
          scenario: scenarioName,
          overflowX: root.scrollWidth - root.clientWidth,
          shellOverlap: shell && content ? Math.max(0, shell.right - content.left) : 0,
          clippedControls: [...document.querySelectorAll("a, button")].filter((node) => node.scrollWidth > node.clientWidth + 2).length,
          statsCompact: scenarioName === "forbidden" ? stats.length === 0 : stats.length === 3 && stats.every((box) => box.height <= 100),
          tableWide: !table || table.width >= 760,
          sensitiveVisible: forbidden.some((value) => text.toLowerCase().includes(value.toLowerCase())),
          normalReady: text.includes("客户访谈洞察整理") && text.includes("项目复盘方法模板") && text.includes("候选证据"),
          noKbReady: text.includes("创建个人知识库"),
          emptyReady: text.includes("还没有个人资料"),
          noProjectReady: text.includes("暂无可用项目"),
          forbiddenReady: text.includes("当前身份无法使用个人知识") && !text.includes("客户访谈洞察整理"),
          listErrorReady: text.includes("个人资料暂时无法加载"),
          writeErrorReady: text.includes("确认失败，请稍后重试"),
        };
      }, scenario);

      Object.assign(result, {
        unexpectedCalls,
        consoleLeak: browserMessages.some((message) => /secret_|SECRET-LIKE|secret-model-ref/.test(message)),
      });
      const statePassed = result[`${scenario.replace(/-([a-z])/g, (_, c) => c.toUpperCase())}Ready`];
      result.passed = result.overflowX <= 1 && result.shellOverlap <= 1 && result.clippedControls === 0 && result.statsCompact && result.tableWide && !result.sensitiveVisible && !result.consoleLeak && result.unexpectedCalls === 0 && Boolean(statePassed);
      await page.screenshot({ path: path.join(outDir, `${scenario}-${viewport.name}.png`), fullPage: false, animations: "disabled" });
      results.push({ viewport: viewport.name, ...result });
      await context.close();
    }
  }
} finally {
  await browser?.close();
  await server?.close();
}

fs.writeFileSync(path.join(outDir, "report.json"), JSON.stringify(results, null, 2));
console.log(JSON.stringify({ port, outDir, results }, null, 2));
const failed = results.filter((result) => !result.passed);
if (failed.length) throw new Error(`PBC-82 personal knowledge UI QA failed in ${failed.length} scenario(s)`);
