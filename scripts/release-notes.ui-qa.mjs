// Real browser workflows against deterministic API fixtures. No production data is used.
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawn } from "node:child_process";
import { chromium } from "playwright";

const base = process.env.UI_QA_BASE || "http://127.0.0.1:5186";
const out = path.join(
  process.env.UI_QA_OUT_DIR || path.join(os.tmpdir(), "kap-ui-qa"),
  "release-notes",
);
fs.mkdirSync(out, { recursive: true });
const server = process.env.UI_QA_BASE
  ? null
  : spawn(
      process.execPath,
      ["node_modules/vite/bin/vite.js", "--host", "127.0.0.1", "--port", "5186", "--strictPort"],
      { stdio: "pipe", windowsHide: true },
    );
let serverOutput = "";
server?.stdout.on("data", (data) => {
  serverOutput = (serverOutput + data).slice(-4000);
});
server?.stderr.on("data", (data) => {
  serverOutput = (serverOutput + data).slice(-4000);
});
let browser;
const reports = [];
const seed = {
  id: "note-one",
  version: "v1.8.0",
  title: "上传与批量确认体验升级",
  entries: [
    { kind: "new", text: "按缺失信息筛选待确认文件，优先处理需要补充的内容。" },
    { kind: "improved", text: "大批量文件浏览更流畅，批量确认无需逐条等待。" },
    { kind: "fixed", text: "人工修改主题后，预览名称和最终入库名称同步更新。" },
  ],
  notify_users: true,
  revision: 2,
  created_at: "2026-09-20T01:00:00Z",
  updated_at: "2026-09-20T01:00:00Z",
  published_at: "2026-09-20T01:00:00Z",
  is_unread: true,
};

async function layout(page, name) {
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth > window.innerWidth + 1,
  );
  assert.equal(overflow, false, `${name}: horizontal page overflow`);
  const dialog = page.getByRole("dialog");
  if (await dialog.count()) {
    const box = await dialog.first().boundingBox();
    assert(
      box.x >= 0 && box.x + box.width <= page.viewportSize().width + 1,
      `${name}: dialog outside viewport`,
    );
    assert.equal(
      await dialog.first().evaluate((el) => el.scrollWidth > el.clientWidth + 1),
      false,
      `${name}: dialog overflow`,
    );
  }
  await page.screenshot({ path: path.join(out, `${name}.png`), fullPage: true });
  const parts = name.split("-");
  const viewport = parts.pop();
  reports.push({ scenario: parts.join("-"), viewport, passed: true });
}

try {
  let ready = false;
  for (let i = 0; i < 80; i++) {
    if (server && server.exitCode !== null) throw new Error(serverOutput);
    try {
      ready = (await fetch(base, { signal: AbortSignal.timeout(500) })).ok;
    } catch {}
    if (ready) break;
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  assert(ready, "UI server not ready");
  browser = await chromium.launch();
  for (const width of [1440, 1024, 390, 360]) {
    const context = await browser.newContext({
      viewport: { width, height: width < 600 ? 844 : 1000 },
    });
    let role = "admin";
    let notes = [
      { ...seed },
      { ...seed, id: "note-two", version: "v1.7.0", title: "知识详情统一展示", is_unread: false },
    ];
    let reads = [];
    let adminCalls = 0;
    let failList = false;
    let publishes = 0;
    await context.route("**/api/v1/**", async (route) => {
      const req = route.request();
      const url = new URL(req.url());
      const p = url.pathname;
      const send = (body, status = 200) =>
        route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
      if (p === "/api/v1/auth/me")
        return send({
          user_id: "release-qa-user",
          name: role === "admin" ? "系统管理员" : "博维顾问",
          email: "qa@example.test",
          status: "active",
          company_roles: [role],
          active_company_role: role,
          is_business_user: role !== "admin",
          can_discover_l5: false,
          project_memberships: [],
        });
      if (p === "/api/v1/auth/csrf") return send({ csrf_token: "local-fixture" });
      if (p === "/api/v1/notifications")
        return send({ items: [], total: 0, unread_count: 0, categories: [] });
      if (p === "/api/v1/notifications/unread-count") return send({ unread_count: 0 });
      if (p === "/api/v1/workbench/overview")
        return send({
          task_center: {
            status: "empty",
            summary: { needs_action: 0, running: 0, attention: 0, completed_today: 0 },
            priority_items: [],
            my_tasks: [],
            running_jobs: [],
            attention_items: [],
            recent_completed: [],
          },
          todos: { status: "empty", items: [], total: 0 },
          operations: { status: "empty", data: null },
          projects: { status: "empty", items: [], total: 0 },
          recent_activity: { status: "empty", items: [], total: 0 },
        });
      const status = () => ({
        running_version: "0.1.0",
        unread_count: notes.filter((n) => n.published_at && n.is_unread).length,
      });
      if (p === "/api/v1/release-notes/status") return send(status());
      if (p === "/api/v1/release-notes/read") {
        reads.push(...req.postDataJSON().release_ids);
        notes = notes.map((n) => (reads.includes(n.id) ? { ...n, is_unread: false } : n));
        return send(status());
      }
      if (p === "/api/v1/release-notes") {
        if (failList) return send({ detail: "offline" }, 503);
        const items = notes.filter((n) => n.published_at);
        return send({ items, total: items.length, page: 1, page_size: 10 });
      }
      if (p.startsWith("/api/v1/admin/release-notes")) {
        adminCalls++;
        if (role !== "admin") return send({ detail: "forbidden" }, 403);
        if (req.method() === "GET") {
          const items = notes.filter((n) =>
            url.searchParams.get("state") === "published"
              ? Boolean(n.published_at)
              : !n.published_at,
          );
          return send({ items, total: items.length, page: 1, page_size: 10 });
        }
        const body = req.postDataJSON();
        if (p.endsWith("/publish")) {
          publishes++;
          const note = notes.find((n) => p.includes(n.id));
          assert.equal(body.revision, note.revision);
          Object.assign(note, {
            published_at: "2026-09-20T02:00:00Z",
            revision: note.revision + 1,
          });
          return send(note);
        }
        const note = {
          ...seed,
          ...body,
          id: "note-created",
          revision: 1,
          published_at: null,
          is_unread: false,
        };
        notes.push(note);
        return send(note, 201);
      }
      return send({ detail: "unhandled UI fixture" }, 404);
    });
    const page = await context.newPage();
    const errors = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await page.goto(base + "/release-notes");
    await page.getByRole("heading", { name: seed.title }).waitFor();
    await page.waitForFunction(() => !document.querySelector(".release-unread-dot"));
    assert.deepEqual(reads, ["note-one"]);
    await layout(page, `reader-${width}`);
    await page.goto(base + "/admin/release-notes");
    await page.getByRole("heading", { name: "从一次值得记录的改进开始" }).waitFor();
    await layout(page, `admin-empty-${width}`);
    await page.getByRole("button", { name: "新建日志" }).first().click();
    await page.getByLabel("版本号", { exact: true }).fill("v1.8.1");
    await page.getByLabel("更新标题", { exact: true }).fill("文件预览体验优化");
    await page
      .getByLabel("第 1 条内容", { exact: true })
      .fill("增加版本日志入口，让每次更新都有清晰记录。");
    await page.getByRole("button", { name: "添加一条" }).click();
    await page
      .getByLabel("第 2 条内容", { exact: true })
      .fill("优化文件预览的加载体验，保留列表中的浏览位置。");
    await layout(page, `editor-${width}`);
    await page.getByRole("button", { name: "预览并发布" }).click();
    await page.getByRole("dialog", { name: "发布预览" }).waitFor();
    assert.equal(publishes, 0);
    await layout(page, `preview-${width}`);
    assert.equal(await page.getByRole("button", { name: "确认发布" }).isDisabled(), true);
    await page.getByRole("button", { name: "保存草稿" }).click();
    await page.getByText("草稿已保存", { exact: true }).first().waitFor();
    await page.getByRole("button", { name: "关闭弹窗" }).click();
    // Simulate a successful deployment registration, not an automatic approval.
    const deployedDraft = notes.find((n) => n.id === "note-created");
    Object.assign(deployedDraft, {
      source_commit: "a".repeat(40),
      deployed_at: "2026-09-20T01:30:00Z",
      revision: 2,
    });
    await page.reload();
    await page.getByRole("button", { name: /文件预览体验优化/ }).click();
    await page.getByRole("button", { name: "预览并发布" }).click();
    await page.getByRole("button", { name: "确认发布" }).click();
    await page.getByText("版本日志已发布，所有登录用户均可查看。").waitFor();
    assert.equal(publishes, 1);
    await page.getByRole("button", { name: /文件预览体验优化/ }).waitFor();
    await layout(page, `published-${width}`);
    role = "consultant";
    adminCalls = 0;
    await page.goto(base + "/admin/release-notes");
    await page.getByText("无此入口", { exact: false }).first().waitFor();
    assert.equal(adminCalls, 0);
    await layout(page, `forbidden-${width}`);
    failList = true;
    await page.goto(base + "/release-notes");
    await page.getByRole("alert").filter({ hasText: "更新日志暂时无法加载" }).waitFor();
    await layout(page, `error-${width}`);
    failList = false;
    notes = [];
    await page.getByRole("button", { name: "重试", exact: true }).click();
    await page.getByRole("heading", { name: "还没有发布更新日志" }).waitFor();
    await layout(page, `empty-${width}`);
    assert.deepEqual(errors, []);
    await context.close();
  }
  fs.writeFileSync(path.join(out, "report.json"), JSON.stringify(reports, null, 2));
  console.log(`${reports.length} browser checks passed. Artifacts: ${out}`);
} finally {
  await browser?.close();
  server?.kill();
}
