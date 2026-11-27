import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { randomUUID } from "node:crypto";
import { chromium } from "playwright";

// UI-only deterministic transport. Backend authorization/runtime has separate pytest coverage.
const base = process.env.UI_QA_BASE || "http://127.0.0.1:5198";
const out = path.join(
  process.env.UI_QA_OUT_DIR || path.join(os.tmpdir(), "kap-ui-qa"),
  "ai-workspace",
);
fs.mkdirSync(out, { recursive: true });
const browser = await chromium.launch();
const cases = [];
try {
  for (const [width, height] of [
    [320, 960],
    [390, 960],
    [768, 960],
    [1024, 960],
    [1440, 960],
    [1024, 600],
  ]) {
    const context = await browser.newContext({ viewport: { width, height } });
    const page = await context.newPage();
    const errors = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await page.clock.install();
    const now = "2026-11-27T04:00:00Z";
    let session = null;
    let messages = [],
      runs = [],
      artifacts = [],
      events = [];
    const emit = (run, type, label) =>
      events.push({ id: events.length + 1, run_id: run.id, type, label, created_at: now });
    const complete = (run) => {
      run.status = "completed";
      run.finished_at = now;
      messages.push({
        id: randomUUID(),
        role: "assistant",
        run_id: run.id,
        created_at: now,
        content:
          "已整理成文档，可以在右侧继续编辑。\n\n" +
          "这是一段用于验收阅读位置的合成内容。\n\n".repeat(18),
      });
      emit(run, "completed", "任务已完成");
    };
    await context.route(/\/api\/v1\//, async (route) => {
      const url = new URL(route.request().url());
      const p = url.pathname;
      const method = route.request().method();
      let body = {},
        status = 200;
      if (p.endsWith("/auth/me"))
        body = {
          user_id: "00000000-0000-0000-0000-000000000064",
          name: "验收用户",
          status: "active",
          company_roles: ["consultant"],
          active_company_role: "consultant",
          is_business_user: true,
          can_discover_l5: false,
          project_memberships: [],
        };
      else if (p.endsWith("/auth/csrf")) body = { csrf_token: "synthetic-test" };
      else if (p.endsWith("/ai-workspace/options"))
        body = {
          models: [{ model_ref: "system_default", display_name: "验收模型", is_default: true }],
          contexts: [{ key: "company", label: "公司知识库" }],
          tools: [
            {
              key: "search_knowledge",
              label: "查找资料",
              description: "在选定知识库中查找有权阅读的摘要",
            },
          ],
        };
      else if (p.endsWith("/ai-workspace/sessions")) {
        if (method === "POST") {
          session = {
            id: route.request().postDataJSON().request_id,
            title: "验收会话",
            created_at: now,
            updated_at: now,
          };
          body = session;
          status = 201;
        } else body = session ? [session] : [];
      } else if (p.endsWith("/messages")) {
        const command = route.request().postDataJSON();
        const run = {
          id: command.request_id,
          status: "running",
          model_ref: command.model_ref,
          context_key: command.context_key,
          error_code: null,
          created_at: now,
          finished_at: null,
        };
        runs.push(run);
        messages.push({
          id: randomUUID(),
          role: "user",
          content: command.content,
          run_id: run.id,
          created_at: now,
        });
        emit(run, "started", "正在理解任务");
        if (runs.length === 1) {
          artifacts.push({
            id: randomUUID(),
            run_id: run.id,
            title: "访谈计划",
            content: "# 项目访谈计划\n\n这是合成验收文档。",
            revision: 1,
            created_at: now,
            updated_at: now,
          });
          complete(run);
        }
        body = run;
        status = 202;
      } else if (p.endsWith("/events")) {
        const after = Number(url.searchParams.get("after") || 0);
        const entries = events.filter((event) => event.id > after).slice(0, 100);
        body = { events: entries, cursor: entries.at(-1)?.id ?? after };
      } else if (p.includes("/artifacts/") && method === "PATCH") {
        const command = route.request().postDataJSON();
        const artifact = artifacts.find((item) => p.endsWith(item.id));
        assert.equal(command.expected_revision, artifact.revision);
        Object.assign(artifact, {
          title: command.title,
          content: command.content,
          revision: artifact.revision + 1,
        });
        body = artifact;
        emit(
          runs.find((run) => run.id === artifact.run_id),
          "artifact_updated",
          "文档修改已保存",
        );
      } else if (p.endsWith("/stop")) {
        const run = runs.at(-1);
        run.status = "stopped";
        run.finished_at = now;
        emit(run, "stopped", "任务已停止");
        body = run;
      } else if (p.endsWith("/retry")) {
        const run = {
          ...runs.at(-1),
          id: route.request().postDataJSON().request_id,
          status: "running",
          finished_at: null,
        };
        runs.push(run);
        emit(run, "started", "正在理解任务");
        body = run;
        status = 202;
      } else if (/\/ai-workspace\/sessions\/[^/]+$/.test(p)) {
        if (method === "DELETE") {
          session = null;
          messages = [];
          runs = [];
          artifacts = [];
          events = [];
          status = 204;
        } else if (method === "PATCH") {
          session.title = route.request().postDataJSON().title;
          body = session;
        } else body = { session, messages, runs, artifacts };
      } else throw new Error(`Unexpected QA API route: ${method} ${p}`);
      await route.fulfill({
        status,
        contentType: "application/json",
        ...(status === 204 ? {} : { body: JSON.stringify(body) }),
      });
    });
    const nav = async (name) => {
      if (width < 1040) await page.getByRole("button", { name: "打开导航", exact: true }).click();
      await page.getByRole("button", { name, exact: true }).click();
    };
    const noOverflow = async () =>
      assert.ok(
        await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1),
        `horizontal overflow at ${width}`,
      );
    await page.goto(`${base}/ai-workspace`);
    await page.getByRole("heading", { name: "今天，想推进什么？" }).waitFor();
    const contextAction = page.getByRole("button", { name: "添加上下文", exact: true });
    assert.equal(
      (await contextAction.textContent()).trim(),
      "",
      "context action must be icon-only",
    );
    assert.equal(await contextAction.locator("svg").count(), 1);
    assert.equal(await page.getByRole("tooltip").count(), 0);
    await page.getByLabel("消息", { exact: true }).focus();
    await contextAction.hover();
    await page.getByRole("tooltip", { name: "添加上下文", exact: true }).waitFor();
    const tooltipBounds = await page.getByRole("tooltip").boundingBox();
    assert.ok(
      tooltipBounds.x >= 0 &&
        tooltipBounds.x + tooltipBounds.width <= width &&
        tooltipBounds.y >= 0 &&
        tooltipBounds.y + tooltipBounds.height <= height,
      `tooltip leaves viewport at ${width}x${height}`,
    );
    if (width === 1440) {
      await page.screenshot({ path: path.join(out, "toolbar-tooltip-1440.png") });
    }
    await page.keyboard.press("Escape");
    await page.getByRole("tooltip").waitFor({ state: "detached" });
    await page.mouse.move(1, 1);
    await contextAction.focus();
    await page.getByRole("tooltip", { name: "添加上下文", exact: true }).waitFor();
    assert.ok(await contextAction.getAttribute("aria-describedby"));
    await page.keyboard.press("Escape");
    await page.getByRole("tooltip").waitFor({ state: "detached" });
    await page.getByLabel("对话模型").selectOption("system_default");
    await page.getByLabel("消息", { exact: true }).focus();
    await page.clock.fastForward(200);
    assert.equal(await page.locator(".app-layout").count(), 0);
    if (width < 1040) {
      const trigger = page.getByRole("button", { name: "打开导航", exact: true });
      await trigger.click();
      await page.getByRole("dialog", { name: "工作空间导航" }).waitFor();
      await page.keyboard.press("Escape");
      await page.waitForFunction(
        () => document.activeElement?.getAttribute("aria-label") === "打开导航",
      );
    }
    await noOverflow();
    await page.screenshot({ path: path.join(out, `home-${width}.png`) });
    await nav("Agent");
    await page.getByText("知识维护 Agent", { exact: true }).click();
    await page.getByRole("link", { name: "打开知识维护 Agent" }).waitFor();
    await noOverflow();
    await page.screenshot({ path: path.join(out, `agents-${width}.png`) });
    await nav("新建会话");
    await page.getByLabel("消息", { exact: true }).fill("请整理访谈计划");
    await page.getByRole("button", { name: "发送消息" }).click();
    await page.getByRole("button", { name: /访谈计划.*文档/ }).click();
    await page.getByRole("tab", { name: "编辑", exact: true }).click();
    await page
      .getByLabel("文档正文", { exact: true })
      .fill("# 我的未保存修改\n\n继续保留这段编辑。");
    const inputNode = await page.getByLabel("文档正文", { exact: true }).elementHandle();
    await noOverflow();
    await page.screenshot({ path: path.join(out, `preview-${width}.png`) });
    if (width < 900) await page.getByRole("button", { name: "关闭预览" }).click();
    await page.getByLabel("消息", { exact: true }).fill("继续完善");
    await page.getByRole("button", { name: "发送消息" }).click();
    await page.getByRole("button", { name: "停止处理" }).waitFor();
    await page.getByLabel("消息", { exact: true }).fill("这条消息暂时不发送");
    await page.locator(".aw-chat-scroll").evaluate((el) => {
      el.scrollTop = 120;
      el.dispatchEvent(new Event("scroll"));
    });
    const scrollTop = await page.locator(".aw-chat-scroll").evaluate((el) => el.scrollTop);
    complete(runs.at(-1));
    await page.clock.fastForward(2500);
    await page.getByRole("button", { name: "发送消息" }).waitFor();
    assert.equal(await page.getByLabel("消息", { exact: true }).inputValue(), "这条消息暂时不发送");
    assert.ok(
      await inputNode.evaluate((el) => el.isConnected),
      "preview editor remounted on completion",
    );
    assert.equal(await page.locator(".aw-chat-scroll").evaluate((el) => el.scrollTop), scrollTop);
    if (width < 900) await page.getByRole("button", { name: "打开文档预览" }).click();
    assert.match(await page.getByLabel("文档正文", { exact: true }).inputValue(), /我的未保存修改/);
    await page.getByRole("button", { name: "保存修改", exact: true }).click();
    await page.getByText("已保存到当前会话", { exact: true }).waitFor();
    assert.equal(artifacts[0].revision, 2);
    await page.getByRole("button", { name: "关闭预览" }).click();
    assert.equal(
      await page.getByRole("tooltip", { name: "关闭预览", exact: true }).count(),
      0,
      "closed preview left its tooltip",
    );
    await page.getByRole("button", { name: "发送消息" }).click();
    await page.getByRole("button", { name: "停止处理" }).click();
    await page.getByRole("button", { name: "重新执行" }).last().click();
    await page.getByRole("button", { name: "停止处理" }).waitFor();
    complete(runs.at(-1));
    await page.clock.fastForward(2500);
    await page.getByRole("button", { name: "发送消息" }).waitFor();
    // Revoking a source does not append a workspace event; projection still updates.
    artifacts = [];
    await page.clock.fastForward(17000);
    await page.locator(".aw-artifact-link").waitFor({ state: "detached" });
    await page.getByRole("button", { name: "删除会话", exact: true }).click();
    await page.getByRole("button", { name: "确认删除", exact: true }).click();
    await page.getByRole("heading", { name: "今天，想推进什么？" }).waitFor();
    await noOverflow();
    assert.deepEqual(errors, []);
    cases.push({
      width,
      height,
      standalone: true,
      state_preserved: true,
      edit_save: true,
      stop_retry_delete: true,
      revoke_without_event: true,
    });
    await context.close();
  }
} finally {
  fs.writeFileSync(path.join(out, "report.json"), JSON.stringify(cases, null, 2));
  await browser.close();
}
console.log(JSON.stringify({ passed: true, cases: cases.length, output: out }));
