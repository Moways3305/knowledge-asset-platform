import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { chromium } from "playwright";

const base = process.env.UI_QA_BASE || "http://127.0.0.1:5188";
const out = path.join(
  process.env.UI_QA_OUT_DIR || path.join(os.tmpdir(), "kap-ui-qa"),
  "knowledge-trust",
);
fs.mkdirSync(out, { recursive: true });
const browser = await chromium.launch({ args: ["--disable-gpu"] });
const cases = [];
const maintenanceActions = [
  {
    id: "asset-corrections",
    label: "处理纠错",
    section: "corrections",
    heading: "trust-corrections-heading",
    button: "已更新，交给提出者验证",
  },
  {
    id: "asset-verify",
    label: "验证处理结果",
    section: "verify",
    heading: "trust-corrections-heading",
    button: "验证已解决",
  },
  {
    id: "asset-review",
    label: "安排或完成复核",
    section: "review",
    heading: "trust-review-heading",
    button: "保存维护安排",
  },
];
try {
  for (const width of [1440, 1024, 390]) {
    for (const scenario of ["normal", "empty", "failure"]) {
      const context = await browser.newContext({ viewport: { width, height: 1000 } });
      await context.route("**/api/**", async (route) => {
        const url = new URL(route.request().url());
        let body = { items: [], total: 0, unread_count: 0 };
        let status = 200;
        if (url.pathname === "/api/v1/auth/me")
          body = {
            user_id: "reader",
            name: "验收用户",
            status: "active",
            company_roles: ["consulting_director"],
            active_company_role: "consulting_director",
            is_business_user: true,
            can_discover_l5: true,
            project_memberships: [],
          };
        if (url.pathname === "/api/v1/knowledge-maintenance") {
          body = {
            page: 1,
            page_size: 25,
            total: scenario === "normal" ? maintenanceActions.length : 0,
            items:
              scenario === "normal"
                ? maintenanceActions.map((item) => ({
                    asset_id: item.id,
                    title: `项目交付模板与管理制度 · ${item.label}`,
                    scope: "company",
                    review_due_at: "2026-10-01T00:00:00Z",
                    freshness: "due",
                    needs_correction: item.section === "corrections",
                    awaiting_my_verification: item.section === "verify",
                  }))
                : [],
          };
          if (scenario === "failure") {
            status = 503;
            body = { detail: { message: "维护服务暂时不可用，请重试。" } };
          }
        }
        const item = maintenanceActions.find(
          (action) =>
            url.pathname === `/api/v1/knowledge/${action.id}` ||
            url.pathname === `/api/v1/knowledge/${action.id}/trust`,
        );
        if (item && url.pathname.endsWith("/trust")) {
          body = {
            asset_id: item.id,
            updated_at: "2026-10-01T00:00:00Z",
            maintainer_user_id: "reader",
            maintainer_name: "验收维护人",
            review_due_at: "2026-11-01T00:00:00Z",
            verified_at: null,
            freshness: "due",
            replacement_asset_id: null,
            can_manage: item.section !== "verify",
            maintainers: [{ id: "reader", name: "验收维护人" }],
            corrections:
              item.section === "review"
                ? []
                : [
                    {
                      id: `correction-${item.id}`,
                      status: item.section === "verify" ? "resolved" : "open",
                      description: "虚构验收纠错内容",
                      resolution: item.section === "verify" ? "虚构验收处理说明" : null,
                      updated_at: "2026-10-01T00:00:00Z",
                      can_resolve: item.section === "corrections",
                      can_verify: item.section === "verify",
                    },
                  ],
          };
        } else if (item) {
          body = {
            id: item.id,
            title: `项目交付模板与管理制度 · ${item.label}`,
            scope: "company",
            zone: "asset",
            asset_type: "methodology",
            confidentiality_level: "L2",
            ai_access_level: "A2",
            asset_status: "active",
            visibility: "company",
            tags: [],
            project_id: null,
            project_name: null,
            lifecycle_phase: null,
            confidence: null,
            last_called_at: null,
            updated_at: "2026-10-01T00:00:00Z",
            archived_at: null,
            archive_reason: null,
            summary: {
              one_liner: "虚构维护验收摘要",
              detailed: "用于验证维护待办分区入口。",
              key_points: [],
            },
            current_version: null,
            access_info: {
              discovery: true,
              summary: true,
              original: false,
              effective_source: "company_role",
              can_request_original: false,
              existing_request_status: null,
              existing_grant_expires_at: null,
              can_delete: false,
              can_manage_lifecycle: false,
              can_retry_index: false,
            },
          };
        }
        assert.equal(
          route.request().method(),
          "GET",
          "maintenance navigation must not submit changes",
        );
        await route.fulfill({
          status,
          contentType: "application/json",
          body: JSON.stringify(body),
        });
      });
      const page = await context.newPage();
      await page.goto(`${base}/knowledge-maintenance`, { waitUntil: "networkidle" });
      await page.getByRole("heading", { name: "知识维护", exact: true }).waitFor();
      if (scenario === "normal") {
        for (const item of maintenanceActions) {
          const action = page.getByRole("link", { name: item.label, exact: true });
          await action.waitFor();
          const target = `/knowledge/${item.id}?maintenance=${item.section}`;
          assert.equal(await action.getAttribute("href"), target);
          const box = await action.boundingBox();
          assert(box && box.x >= 0 && box.x + box.width <= width + 1);
          await action.click();
          await page.waitForURL(`${base}${target}`);
          const dialog = page.getByRole("dialog", { name: "知识维护与复核", exact: true });
          await dialog.waitFor();
          await dialog.locator(`#${item.heading}`).waitFor();
          await page.waitForFunction(
            (heading) => document.activeElement?.id === heading,
            item.heading,
          );
          assert(await dialog.getByRole("button", { name: item.button, exact: true }).isVisible());
          if (item.section === "review")
            assert(await dialog.locator("details").evaluate((element) => element.open));
          if (item.section === "verify")
            assert.equal(
              await dialog.getByRole("button", { name: "保存维护安排", exact: true }).count(),
              0,
            );
          assert.equal(
            await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1),
            false,
          );
          await page.screenshot({
            path: path.join(out, `${item.section}-${width}.png`),
            fullPage: true,
            animations: "disabled",
          });
          await page.goto(`${base}/knowledge-maintenance`, { waitUntil: "networkidle" });
        }
      }
      if (scenario === "empty") await page.getByText("暂无待办。", { exact: false }).waitFor();
      if (scenario === "failure")
        await page.getByRole("button", { name: "重试", exact: true }).waitFor();
      assert.equal(
        await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1),
        false,
      );
      await page.screenshot({
        path: path.join(out, `${scenario}-${width}.png`),
        fullPage: true,
        animations: "disabled",
      });
      cases.push({ scenario, viewport: String(width), passed: true });
      await context.close();
    }
  }
} finally {
  await browser.close();
}
fs.writeFileSync(path.join(out, "report.json"), JSON.stringify({ cases }, null, 2));
console.log(JSON.stringify({ passed: true, cases: cases.length, output: out }));
