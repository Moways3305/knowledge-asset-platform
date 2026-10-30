import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { createServer } from "vite";
import { chromium } from "playwright";

// Dedicated local fixtures: no production URL, real credentials or API writes.
const outDir = path.join(
  process.env.UI_QA_OUT_DIR || path.join(os.tmpdir(), "kap-ui-qa"),
  "shell-actions",
);
fs.mkdirSync(outDir, { recursive: true });
const server = await createServer({ server: { host: "127.0.0.1", port: 0 }, logLevel: "warn" });
await server.listen();
const base = server.resolvedUrls.local[0].replace(/\/$/, "");
let browser;
const results = [];
const empty = { status: "empty", error_code: null, items: [], total: 0 };
const overview = {
  task_center: {
    ...empty,
    summary: { needs_action: 0, running: 0, attention: 0, completed_today: 0 },
    priority_items: [],
    my_tasks: [],
    running_jobs: [],
    attention_items: [],
    recent_completed: [],
  },
  todos: empty,
  operations: { ...empty, data: null },
  projects: empty,
  recent_activity: empty,
};
const demo = `<!doctype html><html lang="zh-CN"><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><div id="root"></div>
<script type="module">
import React from '/node_modules/.vite/deps/react.js';
import ReactDOM from '/node_modules/.vite/deps/react-dom_client.js';
import {ActionGroup,FormActions,ActionMenu} from '/src/components/ActionLayout.tsx';
import {ProductPage,PageHeader} from '/src/components/ProductLayout.tsx';
import Button from '/src/components/Button.tsx';
import '/src/layouts/AppLayout.css';
import '/src/styles/experience-system.css';
const e=React.createElement;
ReactDOM.createRoot(document.getElementById('root')).render(e('main',{style:{padding:16}},
  e(ProductPage,null,e(PageHeader,{title:'资料目录与访问管理',description:'在有限的内容宽度内保留可读标题和清楚的主要操作。',actions:e(ActionGroup,{secondary:e(Button,null,'刷新'),primary:e(Button,{variant:'primary'},'新建目录')})})),
  e('div',{style:{position:'fixed',bottom:4,right:4,maxWidth:'calc(100vw - 8px)'}},
    e(ActionMenu,{label:'更多操作'},e(Button,{disabled:true},'不可用操作'),e(Button,{onClick:()=>document.body.dataset.selected='yes'},'导出当前范围内的摘要'),e('a',{href:'#records'},'查看完整记录'))),
  e('button',{style:{marginTop:24}},'外部操作')
));
</script></html>`;

try {
  browser = await chromium.launch({ args: ["--disable-gpu"] });
  const context = await browser.newContext({
    viewport: { width: 929, height: 900 },
    serviceWorkers: "block",
  });
  await context.route("**/*", async (route) => {
    const url = new URL(route.request().url());
    if (url.origin !== base) return route.abort();
    if (url.pathname === "/__shell-actions-qa")
      return route.fulfill({
        contentType: "text/html",
        body: await server.transformIndexHtml(url.pathname, demo),
      });
    if (!url.pathname.startsWith("/api/")) return route.continue();
    const data =
      url.pathname === "/api/v1/auth/me"
        ? {
            user_id: "00000000-0000-0000-0000-000000000090",
            name: "布局验收管理员",
            email: "fixture@example.test",
            status: "active",
            company_roles: ["admin"],
            active_company_role: "admin",
            is_business_user: false,
            can_discover_l5: false,
            project_memberships: [],
          }
        : url.pathname === "/api/v1/workbench/overview"
          ? overview
          : url.pathname === "/api/v1/notifications"
            ? {
                items: [],
                total: 0,
                page: 1,
                page_size: 20,
                unread_count: 0,
                categories: [],
              }
            : { items: [], total: 0 };
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(data),
    });
  });
  const page = await context.newPage();
  page.setDefaultTimeout(15_000);
  const errors = [];
  page.on("pageerror", (error) => {
    errors.push(error.message);
    console.error(error.message);
  });
  await page.goto(`${base}/help`);
  await page.getByRole("heading", { name: "帮助中心" }).waitFor();
  await page.evaluate(() => document.fonts.ready);
  const captureNavigation = async (name) => {
    const metrics = await page.evaluate(() => ({
      width: innerWidth,
      railWidth: document.querySelector(".rail").getBoundingClientRect().width,
      labelsVisible: [...document.querySelectorAll(".rail-label")].every(
        (el) => getComputedStyle(el).display !== "none",
      ),
      collapsed: document.querySelector(".app-layout").classList.contains("is-rail-collapsed"),
      mobileOpen: document.querySelector(".app-layout").classList.contains("is-mobile-nav-open"),
      overflowX: document.documentElement.scrollWidth - innerWidth,
    }));
    assert.equal(metrics.overflowX, 0);
    const screenshot = path.join(outDir, `${name}.png`);
    await page.screenshot({ path: screenshot, animations: "disabled" });
    results.push({ case: name, ...metrics, screenshot, passed: true });
    return metrics;
  };
  let state = await captureNavigation("929-expanded");
  assert.equal(state.railWidth, 248);
  await page.getByRole("button", { name: "折叠主导航", exact: true }).click();
  await page.waitForFunction(
    () => document.querySelector(".rail").getBoundingClientRect().width === 72,
  );
  state = await captureNavigation("929-collapsed");
  assert.equal(state.labelsVisible, false);
  for (const width of [860, 800, 701]) {
    await page.setViewportSize({ width, height: 900 });
    await page.waitForFunction(
      () => !document.querySelector(".app-layout").classList.contains("is-rail-collapsed"),
    );
    await page.waitForFunction(
      (expected) => document.querySelector(".rail").getBoundingClientRect().width === expected,
      width,
    );
    state = await captureNavigation(`${width}-after-collapse`);
    assert.equal(state.railWidth, width);
    assert.equal(state.labelsVisible, true);
  }
  await page.setViewportSize({ width: 929, height: 900 });
  await page.getByRole("button", { name: "折叠主导航", exact: true }).click();
  for (const width of [700, 390, 320]) {
    await page.setViewportSize({ width, height: width === 320 ? 604 : 844 });
    if (
      !(await page
        .locator(".app-layout")
        .evaluate((el) => el.classList.contains("is-mobile-nav-open")))
    ) {
      await page.getByRole("button", { name: "打开导航", exact: true }).click();
    }
    await page.waitForFunction(
      () => document.querySelector(".rail").getBoundingClientRect().left >= -1,
    );
    state = await captureNavigation(`${width}-drawer-after-collapse`);
    assert.equal(state.collapsed, false);
    assert.equal(state.labelsVisible, true);
    assert.ok(state.railWidth >= 260);
  }
  await page.setViewportSize({ width: 861, height: 900 });
  await page.waitForFunction(
    () => !document.querySelector(".app-layout").classList.contains("is-mobile-nav-open"),
  );
  await page.waitForFunction(
    () => document.querySelector(".rail").getBoundingClientRect().width === 248,
  );
  state = await captureNavigation("861-return-desktop");
  assert.equal(state.railWidth, 248);

  for (const viewport of [
    { width: 929, height: 900 },
    { width: 390, height: 844 },
    { width: 320, height: 604 },
  ]) {
    await page.setViewportSize(viewport);
    await page.goto(`${base}/__shell-actions-qa`);
    const trigger = page.getByRole("button", { name: "更多操作", exact: true });
    await trigger.click();
    await page.waitForFunction(
      () => document.activeElement?.textContent === "导出当前范围内的摘要",
    );
    const metrics = await page.locator(".action-menu-panel").evaluate((el) => {
      const rect = el.getBoundingClientRect();
      const heading = document.querySelector(".product-page-heading").getBoundingClientRect();
      return {
        left: rect.left,
        right: rect.right,
        top: rect.top,
        bottom: rect.bottom,
        width: innerWidth,
        height: innerHeight,
        headingHeight: heading.height,
        overflowX: document.documentElement.scrollWidth - innerWidth,
      };
    });
    assert.ok(
      metrics.left >= 0 &&
        metrics.right <= viewport.width &&
        metrics.top >= 0 &&
        metrics.bottom <= viewport.height,
    );
    assert.equal(metrics.overflowX, 0);
    assert.ok(
      metrics.headingHeight < 160,
      "The mobile heading must not inherit a horizontal flex-basis as height",
    );
    const screenshot = path.join(outDir, `actions-${viewport.width}.png`);
    await page.screenshot({ path: screenshot, animations: "disabled" });
    await page.keyboard.press("Escape");
    assert.equal(await trigger.evaluate((el) => el === document.activeElement), true);
    await trigger.click();
    await page.keyboard.press("Tab");
    await page.keyboard.press("Tab");
    assert.equal(await trigger.getAttribute("aria-expanded"), "false");
    assert.equal(
      await page
        .getByRole("button", { name: "外部操作" })
        .evaluate((el) => el === document.activeElement),
      true,
    );
    await trigger.click();
    await page.getByRole("button", { name: "导出当前范围内的摘要" }).click();
    assert.equal(await page.evaluate(() => document.body.dataset.selected), "yes");
    assert.equal(await trigger.getAttribute("aria-expanded"), "false");
    assert.equal(await trigger.evaluate((el) => el === document.activeElement), true);
    await trigger.click();
    await page.getByRole("button", { name: "外部操作" }).click();
    assert.equal(await trigger.getAttribute("aria-expanded"), "false");
    assert.equal(
      await page
        .getByRole("button", { name: "外部操作" })
        .evaluate((el) => el === document.activeElement),
      true,
    );
    results.push({ case: `actions-${viewport.width}`, ...metrics, screenshot, passed: true });
  }
  assert.deepEqual(errors, []);
} finally {
  await browser?.close();
  await server.close();
  fs.writeFileSync(path.join(outDir, "report.json"), JSON.stringify(results, null, 2));
}
console.log(JSON.stringify({ outDir, cases: results.length, passed: true }));
