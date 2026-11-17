import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import os from "node:os";
import { chromium } from "playwright";

const base = process.env.UI_QA_BASE || "http://127.0.0.1:5197";
const out = path.join(process.env.UI_QA_OUT_DIR || path.join(os.tmpdir(), "kap-ui-qa"), "maintenance-background");
fs.mkdirSync(out, {recursive: true});
const browser = await chromium.launch();
const cases = [];
try {
  for (const width of [1440, 1024, 390]) {
    const context = await browser.newContext({viewport: {width, height: 960}});
    const page = await context.newPage();
    await page.clock.install();
    const settings = {model_ref: "system_default", daily_hour: 2, weekly_day: 6, digest_hour: 9, overdue_days: 7, required_tags: [], required_sections: [], similarity_threshold: .85, max_body_chars: 24000};
    const policy = {id: "policy", library_key: "company", name: "公司知识库", enabled: true, content_authorized: true, revision: 1, settings, can_configure: true};
    let runs = Array.from({length: 20}, (_, i) => ({id: `run-${i}`, policy_id: "policy", kind: "full", status: i ? "partial" : "running", can_retry: !!i, target_count: 3050, completed_count: i ? 3047 : 28, incomplete_count: i ? 3 : 0, skipped_count: 0, reasons: {}, started_at: `2026-11-${String(16 - Math.floor(i/2)).padStart(2,"0")}T08:00:00Z`, finished_at: i ? "2026-11-16T08:20:00Z" : null}));
    let hold = null, release, pending = 0, detailCalls = 0, listCalls = 0, deleted = 0;
    const scope = {assessed_at: runs[0].started_at, visible_count: 3051, target_count: 3050, excluded_counts: {archived: 1}};
    await context.route("**/api/**", async route => {
      const p = new URL(route.request().url()).pathname;
      const method = route.request().method();
      let body = {items: [], total: 0, unread_count: 0, pending_count: 0};
      if (p.endsWith("/auth/me")) body = {user_id: "reader", name: "验收用户", status: "active", company_roles: ["boss"], active_company_role: "boss", is_business_user: true, can_discover_l5: true, project_memberships: []};
      if (p.endsWith("/auth/csrf")) body = {csrf_token: "test"};
      if (p.endsWith("/generation/model-options")) body = {default_missing: false, items: [{model_ref: "a".repeat(64), display_name: "知识质量分析", provider: "custom", model_name: "quality", enabled: true, is_default: true}]};
      if (p.endsWith("/maintenance-agent/policies")) body = [policy];
      if (p.endsWith("/policies/company/runs")) { listCalls++; if (hold) { pending++; await hold; } body = runs; }
      if (/\/runs\/run-\d+$/.test(p)) {
        const id = p.split("/").at(-1);
        if (method === "DELETE") { runs = runs.filter(r => r.id !== id); deleted++; body = {deleted_count: 1}; }
        else {
          detailCalls++; if (hold) { pending++; await hold; }
          body = {...runs.find(r => r.id === id), library_key: "company", historical_details_available: true, scope_snapshot: scope, current_scope: scope, content_authorized: true, settings, total: 25, page: 1, page_size: 25,
            items: Array.from({length: 25}, (_, i) => ({asset_id: `asset-${i}`, title: `知识资料 ${i+1}：质量管理与交付要求`, status: "pending", version_id: "v1", current_version_matches: true, coverage: {quality: "in_progress", duplicates: "complete"}, findings: {}, reasons: [], checked_at: null, progress: {body_checked: 12000, body_total: 46000, segments_checked: 2, comparison_checked: 3050, comparison_total: 3050}}))};
        }
      }
      if (p.endsWith("/runs/delete")) { const ids = route.request().postDataJSON().run_ids; runs = runs.filter(r => !ids.includes(r.id)); deleted += ids.length; body = {deleted_count: ids.length}; }
      await route.fulfill({contentType: "application/json", body: JSON.stringify(body)});
    });
    await page.goto(`${base}/agents/knowledge-maintenance?tab=runs`);
    await page.locator(".agent-history-table tbody tr").first().waitFor();
    if (width >= 1024) assert.ok(await page.locator(".agent-history-table tbody tr").first().evaluate(el => el.getBoundingClientRect().height) <= 120);
    await page.screenshot({path: path.join(out, `compact-${width}.png`), fullPage: true});
    await page.getByRole("button", {name: "查看巡检详情"}).first().click();
    await page.getByRole("heading", {name: "逐项检查结果"}).waitFor();
    await page.getByText("核对当前知识库范围", {exact: true}).click();
    await page.getByLabel("检查结果筛选").focus();
    await page.evaluate(() => {
      const summary = [...document.querySelectorAll("summary")].find(el => el.textContent === "核对当前知识库范围");
      const scroll = document.querySelector(".agent-run-drawer .detail-drawer-body") || document.querySelector(".agent-run-drawer");
      scroll.scrollTop = 320;
      window.__backgroundQA = {summary, scroll, top: scroll.scrollTop, active: document.activeElement, activeTop: document.activeElement.getBoundingClientRect().top};
    });
    hold = new Promise(resolve => {release = resolve;});
    const beforeDetail = detailCalls, beforeList = listCalls;
    await page.clock.fastForward(16_000);
    await page.waitForFunction(() => document.querySelector(".agent-report-toolbar button")?.disabled === true);
    // Check while network responses are still pending, not just after React settles.
    assert.ok(pending >= 1);
    assert.equal(await page.evaluate(() => { const q = window.__backgroundQA; return q.summary.isConnected && q.summary.closest("details").open && Math.abs(q.active.getBoundingClientRect().top - q.activeTop) <= 2 && document.activeElement === q.active; }), true);
    runs[0] = {...runs[0], status: "completed", completed_count: 3050, finished_at: "2026-11-16T09:00:00Z"};
    hold = null; release();
    await page.getByRole("button", {name: "刷新详情"}).waitFor();
    await page.waitForFunction(() => !document.querySelector(".agent-report-toolbar button")?.disabled);
    assert.ok(detailCalls > beforeDetail && listCalls > beforeList);
    assert.equal(await page.evaluate(() => { const q = window.__backgroundQA; return q.summary.isConnected && q.summary.closest("details").open && Math.abs(q.active.getBoundingClientRect().top - q.activeTop) <= 2 && document.activeElement === q.active; }), true);
    await page.screenshot({path: path.join(out, `preserved-detail-${width}.png`), fullPage: true});
    await page.getByRole("button", {name: "关闭详情"}).click();
    await page.locator(".agent-history-table tbody tr").first().getByRole("button", {name: "删除", exact: true}).click();
    await page.getByRole("button", {name: "确认删除记录"}).click();
    await page.waitForFunction(() => document.querySelectorAll(".agent-history-table tbody tr").length === 19);
    assert.equal(deleted, 1);
    await page.getByLabel("选择本页已结束记录").check();
    await page.getByRole("button", {name: "删除所选记录"}).click();
    await page.getByRole("button", {name: "确认删除记录"}).click();
    await page.getByText("尚无可查看的巡检记录").waitFor();
    assert.equal(deleted, 20);
    cases.push({width, preserved: true, compact: true, single_and_bulk_delete: true});
    await context.close();
  }
} finally {
  fs.writeFileSync(path.join(out, "report.json"), JSON.stringify(cases, null, 2));
  await browser.close();
}
console.log(JSON.stringify({passed: true, cases: cases.length, output: out}));
