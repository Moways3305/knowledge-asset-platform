import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { chromium } from "playwright";

const base = process.env.UI_QA_BASE || "http://127.0.0.1:5188";
const out = path.join(process.env.UI_QA_OUT_DIR || path.join(os.tmpdir(), "kap-ui-qa"), "knowledge-trust");
fs.mkdirSync(out, { recursive: true });
const browser = await chromium.launch({ args: ["--disable-gpu"] });
const cases = [];
try {
  for (const width of [1440, 1024, 390]) {
    for (const scenario of ["normal", "empty", "failure"]) {
      const context = await browser.newContext({ viewport: { width, height: 1000 } });
      await context.route("**/api/**", async (route) => {
        const url = new URL(route.request().url());
        let body = { items: [], total: 0, unread_count: 0 };
        let status = 200;
        if (url.pathname === "/api/v1/auth/me") body = {
          user_id: "reader", name: "验收用户", status: "active", company_roles: ["consulting_director"],
          active_company_role: "consulting_director", is_business_user: true, can_discover_l5: true,
          project_memberships: [],
        };
        if (url.pathname === "/api/v1/knowledge-maintenance") {
          body = { page: 1, page_size: 25, total: scenario === "normal" ? 1 : 0,
            items: scenario === "normal" ? [{ asset_id: "asset", title: "项目交付模板与管理制度", scope: "company",
              review_due_at: "2026-10-01T00:00:00Z", freshness: "due", needs_correction: true, awaiting_my_verification: false }] : [] };
          if (scenario === "failure") { status = 503; body = { detail: { message: "维护服务暂时不可用，请重试。" } }; }
        }
        await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
      });
      const page = await context.newPage();
      await page.goto(`${base}/knowledge-maintenance`, { waitUntil: "networkidle" });
      await page.getByRole("heading", { name: "知识维护", exact: true }).waitFor();
      if (scenario === "normal") {
        const action = page.getByRole("link", { name: "查看并处理" });
        await action.waitFor();
        const box = await action.boundingBox();
        assert(box && box.x >= 0 && box.x + box.width <= width + 1);
      }
      if (scenario === "empty") await page.getByText("暂无待办。", { exact: false }).waitFor();
      if (scenario === "failure") await page.getByRole("button", { name: "重试", exact: true }).waitFor();
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1), false);
      await page.screenshot({ path: path.join(out, `${scenario}-${width}.png`), fullPage: true });
      cases.push({ scenario, viewport: String(width), passed: true });
      await context.close();
    }
  }
} finally { await browser.close(); }
fs.writeFileSync(path.join(out, "report.json"), JSON.stringify({ cases }, null, 2));
console.log(JSON.stringify({ passed: true, cases: cases.length, output: out }));
