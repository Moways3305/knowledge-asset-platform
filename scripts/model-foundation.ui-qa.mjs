import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { chromium } from "playwright";
import { build, preview } from "vite";

const port = Number(process.env.UI_QA_PORT || 5201);
const base = `http://127.0.0.1:${port}`;
const outDir = path.join(
  process.env.UI_QA_OUT_DIR || path.join(os.tmpdir(), "kap-ui-qa"),
  "model-foundation",
);
fs.mkdirSync(outDir, { recursive: true });

const viewports = [
  { name: "desktop", width: 1440, height: 1080 },
  { name: "mobile-390", width: 390, height: 844 },
];
const scenarios = [
  "overview",
  "external-drawer",
  "weknora-drawer",
  "kb-drawer",
  "kb-modal",
  "migration-result",
  "empty",
  "forbidden",
];

const authMe = {
  user_id: "qa-admin-ref",
  name: "模型配置管理员",
  email: "qa-admin@example.test",
  status: "active",
  company_roles: ["admin"],
  active_company_role: "admin",
  is_business_user: false,
  can_discover_l5: false,
  project_memberships: [],
};

const connections = [
  {
    model_ref: "external-safe-ref",
    display_name: "生产对话模型",
    capability_type: "chat",
    provider: "deepseek",
    model_name: "deepseek-chat",
    enabled: true,
    health_status: "healthy",
    last_test_succeeded_at: "2026-08-11T08:20:00Z",
    last_test_failed_at: null,
    last_error_category: null,
    available_usages: ["content_generation", "project_qa"],
    legacy_adapter: false,
    api_key: "SECRET_API_KEY_86",
  },
  {
    model_ref: "external-backup-ref",
    display_name: "备用对话模型",
    capability_type: "chat",
    provider: "qwen",
    model_name: "qwen-plus",
    enabled: false,
    health_status: "untested",
    last_test_succeeded_at: null,
    last_test_failed_at: null,
    last_error_category: null,
    available_usages: ["content_generation", "project_qa"],
    legacy_adapter: false,
  },
];

const models = [
  {
    model_ref: "embedding-safe-ref",
    name: "通用嵌入模型",
    type: "embedding",
    source: "remote",
    provider: "managed",
    enabled: true,
    is_builtin: false,
    description: null,
    credential_status: "configured",
    model_id: "SECRET_WEKNORA_MODEL_ID_86",
  },
  {
    model_ref: "chat-safe-ref",
    name: "底座兼容模型",
    type: "chat",
    source: "remote",
    provider: "managed",
    enabled: true,
    is_builtin: false,
    description: null,
    credential_status: "configured",
  },
  {
    model_ref: "rerank-safe-ref",
    name: "中文重排模型",
    type: "rerank",
    source: "remote",
    provider: "managed",
    enabled: true,
    is_builtin: false,
    description: null,
    credential_status: "configured",
  },
];

const defaults = {
  embedding: {
    model_ref: "embedding-safe-ref",
    name: "通用嵌入模型",
    type: "embedding",
    provider: "managed",
  },
  chat: {
    model_ref: "chat-safe-ref",
    name: "底座兼容模型",
    type: "chat",
    provider: "managed",
  },
  rerank: {
    model_ref: "rerank-safe-ref",
    name: "中文重排模型",
    type: "rerank",
    provider: "managed",
  },
  multimodal: null,
  updated_at: "2026-08-11T08:00:00Z",
};

const kbConfigs = [
  {
    mapping_id: "SECRET_MAPPING_ID_86",
    scope: "company",
    kb_name: "公司知识底座",
    project_name: null,
    owner_name: null,
    mapping_status: "active",
    chat: defaults.chat,
    embedding: defaults.embedding,
    rerank: defaults.rerank,
    multimodal: null,
    config_error: null,
    migration: null,
  },
  {
    mapping_id: "SECRET_FAILED_MAPPING_ID_86",
    scope: "project",
    kb_name: "交付方法知识库",
    project_name: "交付改进项目",
    owner_name: null,
    mapping_status: "init_failed",
    chat: defaults.chat,
    embedding: defaults.embedding,
    rerank: null,
    multimodal: null,
    config_error: "SECRET_UPSTREAM_ERROR_86",
    migration: {
      job_id: "SECRET_JOB_ID_86",
      job_status: "completed_with_errors",
      total_count: 12,
      success_count: 10,
      completed_count: 8,
      verified_duplicate_count: 2,
      processing_count: 0,
      duplicate_pending_count: 0,
      pending_count: 0,
      failed_count: 2,
      finished_at: "2026-08-11T08:00:00Z",
    },
  },
];

let server;
let browser;
const results = [];
try {
  await build({ logLevel: "warn" });
  server = await preview({
    preview: { host: "127.0.0.1", port, strictPort: true },
    logLevel: "warn",
  });
  browser = await chromium.launch({ args: ["--disable-gpu"] });

  for (const scenario of scenarios) {
    for (const viewport of viewports) {
      const context = await browser.newContext({ viewport });
      const messages = [];
      await context.route("**/*", async (route) => {
        const url = new URL(route.request().url());
        const fulfill = (body, status = 200) =>
          route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
        if (!url.pathname.startsWith("/api/")) return route.continue();
        if (url.pathname === "/api/v1/auth/me") return fulfill(authMe);
        if (url.pathname === "/api/v1/auth/csrf") return fulfill({ csrf_token: "qa-csrf" });
        if (scenario === "forbidden" && url.pathname.includes("/api/v1/admin/")) {
          return fulfill({ detail: { message: "SECRET_FORBIDDEN_BODY_86" } }, 403);
        }
        if (url.pathname === "/api/v1/admin/model-connections") {
          return fulfill({
            items: scenario === "empty" ? [] : connections,
            total: scenario === "empty" ? 0 : connections.length,
            warning: null,
          });
        }
        if (url.pathname === "/api/v1/admin/model-connections/usages/current") {
          return fulfill({
            external_llm_default:
              scenario === "empty"
                ? null
                : {
                    model_ref: "external-safe-ref",
                    display_name: "生产对话模型",
                    capability_type: "chat",
                  },
            dependency_status: scenario === "empty" ? "missing" : "configured",
            dependency_message: "安全状态说明",
            remediation_hint: "请配置可用连接",
          });
        }
        if (url.pathname === "/api/v1/admin/weknora/models") {
          return fulfill({ items: scenario === "empty" ? [] : models });
        }
        if (url.pathname === "/api/v1/admin/weknora/providers") return fulfill({ items: [] });
        if (url.pathname === "/api/v1/admin/weknora/default-models") return fulfill(defaults);
        if (url.pathname === "/api/v1/admin/weknora/kb-configs") {
          return fulfill({ items: scenario === "empty" ? [] : kbConfigs });
        }
        return fulfill({ detail: { message: "UI QA route not configured" } }, 404);
      });

      const page = await context.newPage();
      page.on("console", (message) => messages.push(message.text()));
      page.on("pageerror", (error) => messages.push(error.message));
      await page.goto(`${base}/admin/weknora-models`, { waitUntil: "networkidle" });
      await page.getByRole("heading", { name: "模型与知识库底座" }).waitFor();

      if (scenario === "external-drawer") {
        await page.getByRole("button", { name: "管理外部 LLM" }).click();
        await page.getByRole("dialog", { name: "管理外部 LLM" }).waitFor();
      } else if (scenario === "weknora-drawer") {
        await page.getByRole("button", { name: "管理 WeKnora 模型" }).click();
        await page.getByRole("dialog", { name: "管理 WeKnora 模型" }).waitFor();
      } else if (["kb-drawer", "kb-modal", "migration-result"].includes(scenario)) {
        await page.getByRole("button", { name: "管理知识库配置" }).click();
        const drawer = page.getByRole("dialog", { name: "管理知识库配置" });
        await drawer.waitFor();
        if (scenario === "kb-modal") {
          await drawer.getByRole("button", { name: "配置" }).first().click();
          await page.getByRole("dialog", { name: /配置“公司知识底座”/ }).waitFor();
        } else if (scenario === "migration-result") {
          await drawer.getByRole("button", { name: "查看迁移结果" }).click();
          await page.getByRole("dialog", { name: /迁移结果/ }).waitFor();
        }
      } else if (scenario === "empty") {
        await page.getByRole("button", { name: "管理知识库配置" }).click();
        await page.getByText("没有匹配的知识库").waitFor();
      } else if (scenario === "forbidden") {
        await page.getByRole("alert").waitFor();
      }

      const screenshot = path.join(outDir, `${scenario}-${viewport.name}.png`);
      await page.screenshot({ path: screenshot, animations: "disabled", fullPage: true });
      const metrics = await page.evaluate((scenarioName) => {
        const text = document.body.innerText;
        const secrets = [
          "SECRET_API_KEY_86",
          "SECRET_WEKNORA_MODEL_ID_86",
          "SECRET_MAPPING_ID_86",
          "SECRET_FAILED_MAPPING_ID_86",
          "SECRET_JOB_ID_86",
          "SECRET_UPSTREAM_ERROR_86",
          "SECRET_FORBIDDEN_BODY_86",
        ];
        return {
          scenario: scenarioName,
          overflowX: document.documentElement.scrollWidth - document.documentElement.clientWidth,
          safe: secrets.every((secret) => !text.includes(secret)),
          dialogCount: document.querySelectorAll('[role="dialog"]').length,
          mainHasGrowingRows:
            !document.querySelector('[role="dialog"]') &&
            (Boolean(document.querySelector(".mf-connection-card")) ||
              Boolean(document.querySelector(".mf-kb-drawer-row"))),
          overviewCards: document.querySelectorAll(".mf-overview-card").length,
          hasInternalError: text.includes("UI QA route not configured"),
        };
      }, scenario);
      const expectedDialogs = scenario === "overview" || scenario === "forbidden" ? 0 : 1;
      const scenarioPass =
        metrics.overviewCards === 3 &&
        !metrics.mainHasGrowingRows &&
        metrics.dialogCount === expectedDialogs;
      results.push({
        viewport: viewport.name,
        screenshot,
        ...metrics,
        consoleLeak: messages.some((message) => /secret|api_key|weknora_kb_id/i.test(message)),
        pass:
          metrics.overflowX <= 2 &&
          metrics.safe &&
          !metrics.hasInternalError &&
          scenarioPass &&
          !messages.some((message) => /secret|api_key|weknora_kb_id/i.test(message)),
      });
      await context.close();
    }
  }
} finally {
  await browser?.close();
  await server?.close();
}

const reportPath = path.join(outDir, "report.json");
fs.writeFileSync(reportPath, JSON.stringify(results, null, 2));
console.log(JSON.stringify({ outDir, reportPath, results }, null, 2));
if (results.some((result) => !result.pass)) process.exitCode = 1;
