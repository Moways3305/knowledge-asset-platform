import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { chromium } from "playwright";
import { auditResponsiveLayout } from "./responsive-layout-audit.mjs";

const base = process.env.UI_QA_BASE || "http://127.0.0.1:5197";
const out = path.join(
  process.env.UI_QA_OUT_DIR || path.join(os.tmpdir(), "kap-ui-qa"),
  "supplemental-responsive",
);
fs.mkdirSync(out, { recursive: true });
const browser = await chromium.launch();
const results = [];
try {
  for (const width of [1440, 1024, 390]) {
    const context = await browser.newContext({ viewport: { width, height: 960 } });
    const errors = [];
    await context.route("**/api/**", async (route) => {
      const p = new URL(route.request().url()).pathname;
      let body = { items: [], total: 0, unread_count: 0, pending_count: 0 };
      if (p.endsWith("/auth/me"))
        body = {
          user_id: "fixture-reader",
          name: "布局验收用户",
          status: "active",
          company_roles: ["boss"],
          active_company_role: "boss",
          is_business_user: true,
          can_discover_l5: true,
          project_memberships: [],
        };
      if (p.endsWith("/reviews"))
        body = {
          items: [
            {
              id: "review",
              review_type: "project_ingest_approval",
              status: "approved",
              asset_title: "客户经营诊断与跨部门交付项目的完整复盘资料及质量验证记录",
              project_name: "多事业部经营管理改善与数字化转型咨询项目",
              created_at: "2026-11-15T08:00:00Z",
              reviewed_at: "2026-11-16T08:00:00Z",
              can_decide: false,
            },
          ],
          total: 1,
          page: 1,
          page_size: 20,
        };
      if (p.endsWith("/projects"))
        body = {
          items: [
            {
              id: "project-layout",
              name: "集团多事业部经营管理改善与数字化转型咨询项目",
              client_name: "跨地区企业管理与战略发展协同研究中心",
              status: "active",
              project_role: "project_manager",
              can_manage: true,
            },
          ],
        };
      if (p.endsWith("/auth/workbuddy-token"))
        body = {
          enabled: true,
          bound_user_name: "布局验收用户",
          last_rotated_at: "2026-11-15T08:00:00Z",
          last_connected_at: "2026-11-16T08:00:00Z",
          operations_enabled: true,
        };
      if (p.endsWith("/auth/workbuddy-connectors")) body = { version: "1", artifacts: [] };
      if (p.endsWith("/auth/mcp-oauth/grants"))
        body = {
          items: [
            {
              id: "grant",
              name: "企业知识管理智能体与文档辅助分析平台",
              operations_enabled: true,
              expires_at: "2026-12-16T08:00:00Z",
            },
          ],
        };
      await route.fulfill({ contentType: "application/json", body: JSON.stringify(body) });
    });
    const page = await context.newPage();
    page.on("pageerror", (error) => errors.push(error.message));
    for (const [route, label, ready] of [
      [
        "/review/completed",
        "completed-review",
        "客户经营诊断与跨部门交付项目的完整复盘资料及质量验证记录",
      ],
      ["/my/workbuddy", "mcp-access", "企业知识管理智能体与文档辅助分析平台"],
      ["/projects", "project-hub", "集团多事业部经营管理改善与数字化转型咨询项目"],
    ]) {
      await page.goto(`${base}${route}`);
      await page.getByText(ready, { exact: false }).waitFor();
      await auditResponsiveLayout(page, { suite: "supplemental-responsive", caseName: label });
      await page.screenshot({
        path: path.join(out, `${label}-${width}.png`),
        fullPage: true,
        animations: "disabled",
      });
      assert.deepEqual(errors, []);
      results.push({ route, width, passed: true });
    }
    await context.close();
  }
} finally {
  fs.writeFileSync(path.join(out, "report.json"), JSON.stringify(results, null, 2));
  await browser.close();
}
console.log(JSON.stringify({ passed: true, cases: results.length, out }));
