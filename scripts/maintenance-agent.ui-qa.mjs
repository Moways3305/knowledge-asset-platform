import { auditResponsiveLayout } from "./responsive-layout-audit.mjs";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { chromium } from "playwright";

const base = process.env.UI_QA_BASE || "http://127.0.0.1:5188";
const out = path.join(process.env.UI_QA_OUT_DIR || path.join(os.tmpdir(), "kap-ui-qa"), "maintenance-agent");
fs.mkdirSync(out, { recursive: true });
const browser = await chromium.launch({ args: ["--disable-gpu"] });
const cases = [];
let currentPage;
const settings = { model_ref: "system_default", daily_hour: 2, weekly_day: 6, digest_hour: 9, overdue_days: 7, required_tags: [], required_sections: [], similarity_threshold: .85, max_body_chars: 24000 };
const models = { default_missing: false, items: [
  { model_ref: "a".repeat(64), display_name: "通义千问 · 平台默认", provider: "aliyun", model_name: "qwen3.6-plus", enabled: true, is_default: true },
  { model_ref: "b".repeat(64), display_name: "DeepSeek · 质量审核", provider: "deepseek", model_name: "deepseek-chat", enabled: true, is_default: false },
] };
const policy = { id: "policy", library_key: "company", name: "公司知识库", enabled: true, content_authorized: true, revision: 1, settings, last_error: null, can_configure: true };
const item = { id: "issue", asset_id: "asset", title: "项目交付标准与质量复核手册", library_key: "company", rule: "cover_only", category: "quality", status: "open", suspected: true, first_seen_at: "2026-11-16T02:10:00Z", last_seen_at: "2026-11-16T02:10:00Z", updated_at: "2026-11-16T02:10:00Z", snooze_until: null, responsible: [{ id: "reader", name: "张顾问" }], can_act: true };
const run = { id: "run", policy_id: "policy", kind: "full", status: "partial", target_count: 138, completed_count: 132, incomplete_count: 6, skipped_count: 0, reasons: { content_not_authorized: 4, model_unavailable: 2 }, started_at: "2026-11-16T02:00:00Z", finished_at: "2026-11-16T02:20:00Z" };
try {
  for (const width of [1440, 1024, 390]) {
    for (const scenario of ["normal", "empty", "failure", "forbidden", "setup", "readonly", "model_missing", "model_error", "legacy_run", "zero_run"]) {
      const context = await browser.newContext({ viewport: { width, height: 1000 } });
      let actions = 0, saved = 0, maintenanceRequests = 0;
      let currentPolicy = { ...policy };
      const activeRun = ["legacy_run", "zero_run"].includes(scenario) ? { ...run, target_count: 0, completed_count: 0, incomplete_count: 0, reasons: {}, status: scenario === "zero_run" ? "empty" : "completed" } : run;
      const scope = { assessed_at: run.started_at, visible_count: scenario === "zero_run" ? 2 : 140, target_count: activeRun.target_count, excluded_counts: { archived: 2 } };
      const detail = { ...activeRun, last_progress_at: run.finished_at, library_key: "company", historical_details_available: scenario !== "legacy_run", scope_snapshot: scenario === "legacy_run" ? null : scope, current_scope: scope, content_authorized: true, settings, total: activeRun.target_count ? 1 : 0, page: 1, page_size: 25, items: activeRun.target_count ? [{ asset_id: "asset", title: item.title, status: "incomplete", version_id: "v1", current_version_matches: true, coverage: { integrity: "complete", availability: "complete", maintenance: "complete", duplicates: "complete", quality: "model_unavailable" }, findings: { missing_review_date: 1 }, reasons: ["model_unavailable"], checked_at: run.finished_at }] : [] };
      let started = 0;
      if (scenario === "setup") currentPolicy = { ...policy, id: null, revision: 0, enabled: false, content_authorized: false };
      if (scenario === "readonly") currentPolicy = { ...policy, can_configure: false };
      if (scenario === "model_missing") currentPolicy = { ...policy, settings: { ...settings, model_ref: "c".repeat(64) } };
      await context.route("**/api/**", async route => {
        const url = new URL(route.request().url());
        const p = url.pathname;
        let status = 200;
        let body = { items: [], total: 0, unread_count: 0, pending_count: 0 };
        if (p === "/api/v1/auth/me") body = { user_id: "reader", name: "验收用户", status: "active", company_roles: [scenario === "forbidden" ? "admin" : "consulting_director"], active_company_role: scenario === "forbidden" ? "admin" : "consulting_director", is_business_user: scenario !== "forbidden", can_discover_l5: scenario !== "forbidden", project_memberships: [] };
        if (p === "/api/v1/auth/csrf") body = { csrf_token: "test-csrf" };
        if (p.startsWith("/api/v1/maintenance-agent/")) maintenanceRequests += 1;
        if (p === "/api/v1/generation/model-options") {
          body = models;
          if (scenario === "model_error") { status = 503; body = { detail: { message: "模型信息暂时不可用" } }; }
        }
        if (p === "/api/v1/maintenance-agent/policies") body = [currentPolicy];
        if (p === "/api/v1/maintenance-agent/issues") body = { items: ["empty", "setup"].includes(scenario) ? [] : [item], total: ["empty", "setup"].includes(scenario) ? 0 : 1, page: 1, page_size: 25 };
        if (p.endsWith("/policies/company/runs")) {
          body = scenario === "setup" ? (started ? [{ ...run, status: "queued" }] : []) : [activeRun];
          if (route.request().method() === "POST") { started += 1; body = { ...run, status: "queued" }; }
        }
        if (p.endsWith("/policies/company/runs/run")) body = detail;
        if (p.endsWith("/issues/issue")) body = { ...item, evidence: { quote: "目录第一章：交付标准；第二章：质量复核。", offset: 0 }, evidence_available: true, current_version_matches: true, history: [{ action: "detected", reason: "", created_at: item.first_seen_at }] };
        if (p.endsWith("/issues/issue/actions")) {
          const data = route.request().postDataJSON();
          assert.equal(data.expected_updated_at, item.updated_at);
          assert.equal(data.action, "in_progress");
          actions += 1;
          body = { ...item, status: "in_progress", evidence: {}, evidence_available: true, current_version_matches: true, history: [{ action: "in_progress", reason: data.reason, created_at: item.first_seen_at }] };
        }
        if (p.endsWith("/policies/company") && route.request().method() === "PUT") {
          const data = route.request().postDataJSON();
          assert.equal(data.expected_revision, currentPolicy.revision);
          if (scenario === "normal") assert.equal(data.settings.daily_hour, 4);
          assert.equal(data.settings.model_ref, "b".repeat(64));
          saved += 1; currentPolicy = { ...currentPolicy, ...data, id: "policy", revision: currentPolicy.revision + 1 }; body = currentPolicy;
        }
        if (scenario === "failure" && p === "/api/v1/maintenance-agent/issues") { status = 503; body = { detail: { message: "巡检服务暂时不可用，请重试。" } }; }
        await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
      });
      const page = await context.newPage();
      currentPage = page;
      const failures = [];
      page.on("pageerror", error => failures.push(error.message));
      await page.goto(`${base}/agents/knowledge-maintenance`);
      if (scenario === "forbidden") {
        await page.getByText("当前账号无此入口", { exact: true }).waitFor();
        assert.equal(maintenanceRequests, 0);
        assert.equal(await page.getByRole("heading", { name: "知识维护 Agent", exact: true }).count(), 0);
      } else if (scenario === "failure") {
        await page.getByRole("alert").filter({ hasText: "巡检服务暂时不可用" }).waitFor();
      } else if (scenario === "empty") {
        await page.getByRole("heading", { name: "当前筛选下没有维护待办" }).waitFor();
      } else if (scenario === "normal") {
        await page.getByRole("button", { name: "疑似只有封面或目录" }).waitFor();
        const agentNavigation = page.locator('#primary-navigation a[href="/agents"]');
        assert.equal(await agentNavigation.getAttribute("aria-current"), "page");
        assert.equal(await page.locator('#primary-navigation a[href="/knowledge"]').getAttribute("aria-current"), null);
        assert.equal(await page.getByRole("navigation", { name: "知识库导航" }).count(), 0);
        assert.equal(await page.locator('.deck-context a[aria-label="进入智能体中心"]').getAttribute("href"), "/agents");
        if (width === 390) {
          const mobileAgent = page.getByRole("link", { name: "底部智能体中心", exact: true });
          assert.equal(await mobileAgent.isVisible(), true);
          assert.equal(await mobileAgent.getAttribute("aria-current"), "page");
        }
        await auditResponsiveLayout(page, { suite: "maintenance-agent", caseName: typeof scenario === "undefined" ? "normal" : typeof scenario === "string" ? scenario : scenario.name || "normal" });
        await page.screenshot({ path: path.join(out, `issues-normal-${width}.png`), fullPage: true, animations: "disabled" });
        await page.getByRole("button", { name: "疑似只有封面或目录" }).click();
        await page.getByText("目录第一章：交付标准；第二章：质量复核。", { exact: true }).waitFor();
        await auditResponsiveLayout(page, { suite: "maintenance-agent", caseName: typeof scenario === "undefined" ? "normal" : typeof scenario === "string" ? scenario : scenario.name || "normal" });
        await page.screenshot({ path: path.join(out, `detail-normal-${width}.png`), fullPage: true, animations: "disabled" });
        await page.getByLabel("处理原因").fill("正在核对资料正文");
        await page.getByRole("button", { name: "提交处理", exact: true }).click();
        await page.getByRole("button", { name: "关闭详情" }).click();
        assert.equal(actions, 1);
        await page.getByRole("button", { name: "巡检设置", exact: true }).click();
        await page.getByLabel("正文分析模型").selectOption("b".repeat(64));
        await page.getByLabel("每日增量巡检（北京时间）").selectOption("4");
        await page.getByRole("button", { name: "保存巡检设置" }).click();
        await page.getByText("巡检设置已保存。", { exact: true }).waitFor();
        assert.equal(saved, 1);
        await page.locator("main.app-content").evaluate(el => el.scrollTo(0, 0));
        await auditResponsiveLayout(page, { suite: "maintenance-agent", caseName: typeof scenario === "undefined" ? "normal" : typeof scenario === "string" ? scenario : scenario.name || "normal" });
        await page.screenshot({ path: path.join(out, `settings-normal-${width}.png`), fullPage: true, animations: "disabled" });
        await page.getByRole("button", { name: "巡检记录", exact: true }).click();
        await page.getByText("部分未完成", { exact: true }).waitFor();
        await auditResponsiveLayout(page, { suite: "maintenance-agent", caseName: typeof scenario === "undefined" ? "normal" : typeof scenario === "string" ? scenario : scenario.name || "normal" });
        await page.screenshot({ path: path.join(out, `runs-normal-${width}.png`), fullPage: true, animations: "disabled" });
        await page.getByRole("button", { name: "查看巡检详情", exact: true }).click();
        await page.getByRole("heading", { name: "逐项检查结果" }).waitFor();
        await page.getByRole("link", { name: item.title, exact: true }).waitFor();
        await page.getByLabel("检查结果筛选").selectOption("incomplete");
        await page.getByRole("heading", { name: "逐项检查结果" }).waitFor();
        await auditResponsiveLayout(page, { suite: "maintenance-agent", caseName: typeof scenario === "undefined" ? "normal" : typeof scenario === "string" ? scenario : scenario.name || "normal" });
        await page.screenshot({ path: path.join(out, `run-detail-${width}.png`), fullPage: true, animations: "disabled" });
        assert.equal(await page.getByRole("dialog").evaluate(el => el.scrollWidth <= el.clientWidth + 1), true);
        await page.getByRole("button", { name: "关闭详情" }).click();
      }
      if (scenario === "setup") {
        const setup = page.getByRole("button", { name: "配置并开始", exact: true });
        await setup.waitFor();
        await page.locator("button:enabled").filter({ hasText: "配置并开始" }).waitFor();
        assert.equal(await setup.isEnabled(), true);
        await auditResponsiveLayout(page, { suite: "maintenance-agent", caseName: typeof scenario === "undefined" ? "normal" : typeof scenario === "string" ? scenario : scenario.name || "normal" });
        await page.screenshot({ path: path.join(out, `setup-before-${width}.png`), fullPage: true });
        await setup.click();
        await page.getByLabel("正文分析模型").selectOption("b".repeat(64));
        await page.getByLabel("授权检查可访问的原始文件，并使用所选模型分析正文").check();
        await page.locator("main.app-content").evaluate(el => el.scrollTo(0, 0));
        await auditResponsiveLayout(page, { suite: "maintenance-agent", caseName: typeof scenario === "undefined" ? "normal" : typeof scenario === "string" ? scenario : scenario.name || "normal" });
        await page.screenshot({ path: path.join(out, `setup-model-${width}.png`), fullPage: true });
        await page.getByRole("button", { name: "保存并开始巡检", exact: true }).click();
        await page.getByText("巡检已加入后台队列，可在巡检记录中查看进度。", { exact: true }).waitFor();
        assert.equal(saved, 1); assert.equal(started, 1);
        await page.getByRole("button", { name: "关闭详情" }).click();
        await page.getByRole("button", { name: "查看巡检进度", exact: true }).click();
        assert.equal(started, 1);
      }
      if (["legacy_run", "zero_run"].includes(scenario)) {
        await page.getByRole("button", { name: "巡检记录", exact: true }).click();
        await page.getByText("无检查对象", { exact: true }).waitFor();
        await page.getByRole("button", { name: "查看巡检详情" }).click();
        if (scenario === "legacy_run") await page.getByText(/这是一条旧版巡检记录/).waitFor();
        else await page.getByText(/没有符合条件的资料/).first().waitFor();
        await auditResponsiveLayout(page, { suite: "maintenance-agent", caseName: typeof scenario === "undefined" ? "normal" : typeof scenario === "string" ? scenario : scenario.name || "normal" });
        await page.screenshot({ path: path.join(out, `run-${scenario}-${width}.png`), fullPage: true, animations: "disabled" });
        await page.getByRole("button", { name: "关闭详情" }).click();
      }
      if (scenario === "readonly") {
        await page.getByText("需由公司知识治理人员或该项目经理操作", { exact: true }).waitFor();
        assert.equal(await page.getByRole("button", { name: "立即全面巡检", exact: true }).isDisabled(), true);
      }
      if (scenario === "model_missing" || scenario === "model_error") {
        await page.getByRole("button", { name: "巡检设置", exact: true }).click();
        if (scenario === "model_missing") {
          await page.getByText("当前没有可用的分析模型。规则巡检仍可执行，正文质量检查会标记为未完成。", { exact: true }).waitFor();
          assert.equal(await page.getByLabel("正文分析模型").inputValue(), "c".repeat(64));
        } else {
          await page.getByText("模型信息暂时不可用", { exact: true }).waitFor();
          assert.equal(await page.getByRole("button", { name: "重新读取模型" }).isEnabled(), true);
        }
      }
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 2), false, `${scenario} overflow at ${width}`);
      assert.deepEqual(failures, [], `${scenario} JS errors`);
      await auditResponsiveLayout(page, { suite: "maintenance-agent", caseName: typeof scenario === "undefined" ? "normal" : typeof scenario === "string" ? scenario : scenario.name || "normal" });
      await page.screenshot({ path: path.join(out, `maintenance-${scenario}-${width}.png`), fullPage: true, animations: "disabled" });
      cases.push({ page: "maintenance", scenario, viewport: String(width), passed: true });
      if (scenario === "normal") {
        await page.goto(`${base}/agents`);
        await page.getByRole("link", { name: "进入知识维护" }).waitFor();
        await page.getByRole("searchbox", { name: "搜索智能体" }).fill("不存在的应用");
        await page.getByText("没有找到匹配的智能体", { exact: true }).waitFor();
        assert.equal(await page.getByRole("link", { name: "进入知识维护" }).count(), 0);
        await page.getByRole("button", { name: "清空搜索", exact: true }).click();
        await page.getByRole("searchbox", { name: "搜索智能体" }).fill("巡检");
        await page.getByRole("link", { name: "进入知识维护" }).waitFor();
        await page.getByRole("searchbox", { name: "搜索智能体" }).fill("");
        await page.getByRole("heading", { name: "智能体中心", exact: true }).click();
        await page.mouse.move(0, 0);
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 2), false, `center overflow at ${width}`);
        await auditResponsiveLayout(page, { suite: "maintenance-agent", caseName: typeof scenario === "undefined" ? "normal" : typeof scenario === "string" ? scenario : scenario.name || "normal" });
        await page.screenshot({ path: path.join(out, `center-normal-${width}.png`), fullPage: true, animations: "disabled" });
        cases.push({ page: "center", scenario: "normal", viewport: String(width), passed: true });
      }
      await context.close();
    }
  }
} catch (error) {
  if (currentPage && !currentPage.isClosed()) {
    await currentPage.screenshot({ path: path.join(out, "failure-debug.png"), fullPage: true, animations: "disabled" });
    console.error((await currentPage.locator("body").innerText()).slice(0, 5000));
  }
  throw error;
} finally {
  fs.writeFileSync(path.join(out, "report.json"), JSON.stringify({ cases }, null, 2));
  await browser.close();
}
console.log(`Maintenance Agent UI QA: ${cases.length} cases passed; ${out}`);
