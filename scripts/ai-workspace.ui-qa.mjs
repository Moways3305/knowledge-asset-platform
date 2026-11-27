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
    const maintenanceSettings = {
      model_ref: "system_default",
      daily_hour: 2,
      weekly_day: 6,
      digest_hour: 9,
      overdue_days: 7,
      required_tags: [],
      required_sections: [],
      similarity_threshold: 0.85,
      max_body_chars: 24000,
    };
    const historyRun = {
      id: "historical-scan",
      policy_id: "policy",
      kind: "full",
      status: "completed",
      target_count: 12,
      completed_count: 12,
      incomplete_count: 0,
      skipped_count: 0,
      reasons: {},
      started_at: now,
      finished_at: now,
    };
    const scanScope = {
      assessed_at: now,
      visible_count: 12,
      target_count: 12,
      excluded_counts: {},
    };
    let session = null;
    let messages = [],
      runs = [],
      artifacts = [],
      actions = [],
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
      else if (p.endsWith("/maintenance-agent/policies"))
        body = [
          {
            id: "policy",
            library_key: "company",
            name: "公司知识库",
            enabled: false,
            content_authorized: false,
            revision: 1,
            can_configure: true,
            settings: maintenanceSettings,
            last_error: null,
          },
        ];
      else if (p.endsWith("/maintenance-agent/policies/company/runs")) body = [historyRun];
      else if (p.endsWith("/maintenance-agent/policies/company/runs/historical-scan"))
        body = {
          ...historyRun,
          library_key: "company",
          historical_details_available: true,
          scope_snapshot: scanScope,
          current_scope: scanScope,
          content_authorized: false,
          settings: maintenanceSettings,
          items: [
            {
              asset_id: "synthetic-asset",
              title: "合成个人信息核查资料",
              status: "completed",
              version_id: "synthetic-version",
              current_version_matches: true,
              coverage: { integrity: "completed" },
              findings: {},
              reasons: [],
              checked_at: now,
            },
          ],
          total: 1,
          page: 1,
          page_size: 25,
        };
      else if (p.endsWith("/maintenance-agent/issues"))
        body = { items: [], total: 0, page: 1, page_size: 25 };
      else if (p.endsWith("/generation/model-options"))
        body = {
          default_missing: false,
          items: [
            {
              model_ref: "system_default",
              display_name: "验收模型",
              is_default: true,
              enabled: true,
            },
          ],
        };
      else if (p.endsWith("/ai-workspace/options"))
        body = {
          models: [{ model_ref: "system_default", display_name: "验收模型", is_default: true }],
          contexts: [{ key: "company", label: "公司知识库" }],
          agents: [
            {
              key: "knowledge-maintenance",
              label: "知识维护 Agent",
              description: "核对知识、保留依据并持续跟进",
              tools: [
                {
                  key: "start_maintenance_scan",
                  label: "开展巡检",
                  description: "按指定范围检查知识",
                },
              ],
            },
          ],
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
            agent_key: route.request().postDataJSON().agent_key,
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
            title: session.agent_key ? "知识维护报告" : "访谈计划",
            content: "# 项目访谈计划\n\n这是合成验收文档。",
            revision: 1,
            created_at: now,
            updated_at: now,
          });
          if (session.agent_key) {
            run.status = "awaiting_confirmation";
            run.pending_action = {
              id: randomUUID(),
              tool: "request_maintenance_recheck",
              label: "复检已修正的个人信息问题",
              summary:
                "复检公司知识库《合成个人信息核查资料》当前第 2 版。仅在复检通过后关闭对应问题，报告不包含敏感原值。",
              arguments: {
                library_key: "company",
                issue_id: "00000000-0000-0000-0000-000000000011",
                version_id: "00000000-0000-0000-0000-000000000012",
                policy_revision: 2,
              },
            };
            actions.push({
              ...run.pending_action,
              run_id: run.id,
              status: "awaiting_confirmation",
              observation: {},
              created_at: now,
              updated_at: now,
            });
          } else complete(run);
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
      } else if (p.includes("/actions/")) {
        const run = runs.at(-1);
        assert.equal(route.request().postDataJSON().decision, "approve");
        assert.ok(p.endsWith(run.pending_action.id));
        actions.at(-1).status = "completed";
        actions.at(-1).observation = {
          run_id: "synthetic-scan",
          status: "running",
          target_count: 1,
          completed_count: 0,
          receipt_summary: "已提交当前资料第 2 版的复检，等待真实检查结果。",
        };
        run.pending_action = null;
        run.status = "waiting";
        run.waiting_reason = "external_task";
        emit(run, "waiting", "复检已开始，等待后台检查结果");
        body = run;
      } else if (p.endsWith("/resume")) {
        const run = runs.at(-1);
        assert.ok(p.includes(run.id));
        const command = route.request().postDataJSON();
        if (command.content)
          messages.push({
            id: randomUUID(),
            run_id: run.id,
            role: "user",
            content: command.content,
            created_at: now,
          });
        run.status = "running";
        run.finished_at = null;
        emit(run, "started", "从已保存进展继续任务");
        body = run;
        status = 202;
      } else if (/\/ai-workspace\/sessions\/[^/]+$/.test(p)) {
        if (method === "DELETE") {
          session = null;
          messages = [];
          runs = [];
          artifacts = [];
          events = [];
          actions = [];
          status = 204;
        } else if (method === "PATCH") {
          session.title = route.request().postDataJSON().title;
          body = session;
        } else body = { session, messages, runs, artifacts, actions };
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
    const flatSurface = async (selector) => {
      const surface = page.locator(selector).first();
      await surface.waitFor({ state: "visible" });
      assert.deepEqual(
        await surface.evaluate((element) => {
          const style = getComputedStyle(element);
          return {
            background: style.backgroundColor,
            shadow: style.boxShadow,
            radius: style.borderRadius,
            left: style.borderLeftWidth,
            right: style.borderRightWidth,
          };
        }),
        {
          background: "rgba(0, 0, 0, 0)",
          shadow: "none",
          radius: "0px",
          left: "0px",
          right: "0px",
        },
        `${selector} is a card at ${width}`,
      );
    };
    await page.goto(`${base}/ai-workspace`);
    await page.getByRole("heading", { name: "今天，想推进什么？" }).waitFor();
    assert.deepEqual(
      await page.evaluate(async () => {
        await document.fonts.ready;
        return [...document.fonts]
          .filter((font) => font.status === "error")
          .map((font) => font.family);
      }),
      [],
      "workspace fonts failed to load",
    );
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
    const agentPicker = page.getByRole("button", { name: "添加智能体", exact: true });
    assert.equal(
      (await agentPicker.textContent()).trim(),
      "",
      "unselected Agent action is icon-only",
    );
    const draft = page.getByLabel("消息", { exact: true });
    await draft.fill("先保留输入，再选择负责这件事的智能体");
    await agentPicker.click();
    const agentMenu = page.getByRole("menu", { name: "选择智能体", exact: true });
    await agentMenu.waitFor();
    const menuBounds = await agentMenu.boundingBox();
    assert.ok(
      menuBounds.x >= 0 &&
        menuBounds.y >= 0 &&
        menuBounds.x + menuBounds.width <= width &&
        menuBounds.y + menuBounds.height <= height,
      `Agent menu leaves viewport at ${width}x${height}`,
    );
    await page.screenshot({
      path: path.join(out, `agent-picker-${width}-${height}.png`),
      animations: "disabled",
    });
    await page.getByRole("menuitemradio", { name: "知识维护 Agent", exact: true }).click();
    await page.getByRole("heading", { name: "交给我一个知识维护目标" }).waitFor();
    assert.equal(await draft.inputValue(), "先保留输入，再选择负责这件事的智能体");
    assert.ok((await agentPicker.textContent()).includes("知识维护 Agent"));
    assert.equal(context.pages().length, 1);
    await noOverflow();
    await page.screenshot({ path: path.join(out, `agent-selected-${width}-${height}.png`) });
    await agentPicker.click();
    await page.getByRole("menuitemradio", { name: "通用对话", exact: true }).click();
    await page.getByRole("heading", { name: "今天，想推进什么？" }).waitFor();
    assert.equal(await draft.inputValue(), "先保留输入，再选择负责这件事的智能体");
    await draft.fill("");
    await nav("Agent");
    await page.getByText("知识维护 Agent", { exact: true }).click();
    await page.getByRole("link", { name: "开始任务" }).waitFor();
    await flatSurface(".aw-agent-row");
    await noOverflow();
    await page.screenshot({ path: path.join(out, `agents-${width}.png`) });
    await page.getByRole("link", { name: "开始任务" }).click();
    await page.getByRole("heading", { name: "交给我一个知识维护目标" }).waitFor();
    assert.equal(context.pages().length, 1, "Agent entry unexpectedly opened another tab");
    assert.equal(await page.locator(".app-layout").count(), 0, "Agent returned to KAP shell");
    await noOverflow();
    await page.screenshot({ path: path.join(out, `agent-detail-${width}.png`) });
    await page.getByRole("link", { name: "维护待办", exact: true }).click();
    await page.getByRole("button", { name: "维护待办", exact: true }).waitFor();
    await flatSurface(".is-workspace-agent");
    await flatSurface(".agent-panel");
    await flatSurface(".agent-readiness");
    await noOverflow();
    await page.screenshot({
      path: path.join(out, `flat-maintenance-issues-${width}.png`),
      animations: "disabled",
    });
    await page.getByRole("button", { name: "巡检记录", exact: true }).click();
    await page.getByRole("button", { name: "查看巡检详情" }).waitFor();
    await flatSurface(".agent-panel");
    await noOverflow();
    await page.screenshot({
      path: path.join(out, `flat-maintenance-runs-${width}.png`),
      animations: "disabled",
    });
    await page.getByRole("button", { name: "查看巡检详情" }).click();
    await page.getByRole("dialog", { name: "巡检详情" }).waitFor();
    await flatSurface(".is-workspace-detail .agent-report-scope");
    await flatSurface(".is-workspace-detail .agent-run-items article");
    await page.screenshot({
      path: path.join(out, `flat-maintenance-report-${width}.png`),
      animations: "disabled",
    });
    await page.getByRole("button", { name: "关闭详情", exact: true }).click();
    await page.getByRole("button", { name: "巡检设置", exact: true }).click();
    await page.getByRole("heading", { name: "巡检与授权", exact: true }).waitFor();
    await flatSurface(".agent-settings");
    await flatSurface(".agent-authorization");
    await noOverflow();
    await page.screenshot({
      path: path.join(out, `flat-maintenance-settings-${width}.png`),
      animations: "disabled",
    });
    await page.getByRole("button", { name: "返回 Agent 会话", exact: true }).click();
    await nav("工具");
    await page.getByRole("heading", { name: "工作空间工具" }).waitFor();
    await flatSurface(".aw-tool-row");
    await page.screenshot({
      path: path.join(out, `flat-tools-${width}.png`),
      animations: "disabled",
    });
    await nav("新建会话");
    await page.getByRole("heading", { name: "今天，想推进什么？" }).waitFor();
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
    // Enter the business Agent and use browser history back through its catalogue.
    // The chat draft, chosen session and unsaved preview must survive the entire route.
    if (width < 900) await page.getByRole("button", { name: "关闭预览" }).click();
    await nav("Agent");
    await page.getByText("知识维护 Agent", { exact: true }).click();
    await page.getByRole("link", { name: "开始任务" }).click();
    await page.getByRole("heading", { name: "交给我一个知识维护目标" }).waitFor();
    assert.equal(new URL(page.url()).searchParams.get("agent"), "knowledge-maintenance");
    await page.goBack();
    await page.getByRole("heading", { name: "让 Agent 接手一类工作" }).waitFor();
    await page.goBack();
    await page.getByLabel("消息", { exact: true }).waitFor();
    assert.equal(await page.getByLabel("消息", { exact: true }).inputValue(), "这条消息暂时不发送");
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
    await page.getByRole("button", { name: "继续任务" }).last().click();
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
    // A real Agent session uses the same runtime and preview, with an explicit action receipt.
    await nav("Agent");
    await page.getByText("知识维护 Agent", { exact: true }).click();
    await page.getByRole("link", { name: "开始任务" }).click();
    await page
      .getByLabel("消息", { exact: true })
      .fill("请复检《合成个人信息核查资料》第 2 版中已修正的个人信息问题，不复述原值");
    await page.getByRole("button", { name: "发送消息", exact: true }).click();
    await page.getByRole("region", { name: "确认本次操作" }).waitFor();
    await flatSurface(".aw-action-confirmation");
    assert.equal(session.agent_key, "knowledge-maintenance");
    assert.equal(runs[0].context_key, "company");
    assert.equal(await page.getByRole("button", { name: "发送消息", exact: true }).count(), 0);
    await noOverflow();
    await page.screenshot({ path: path.join(out, `agent-confirmation-${width}.png`) });
    const agentRunId = runs[0].id;
    await page.getByRole("button", { name: "确认执行", exact: true }).click();
    await page
      .getByText("后台任务仍在执行，Agent 会自动查看结果。你也可以补充要求。", { exact: true })
      .waitFor();
    await page.getByLabel("消息", { exact: true }).fill("优先检查摘要");
    await page.getByRole("button", { name: "补充并继续", exact: true }).click();
    assert.equal(runs.length, 1);
    assert.equal(runs[0].id, agentRunId);
    complete(runs[0]);
    await page.clock.fastForward(2500);
    await page.getByRole("button", { name: /知识维护报告.*文档/ }).click();
    await page.getByRole("tab", { name: "编辑", exact: true }).click();
    await page.getByLabel("文档正文", { exact: true }).fill("待保存的维护报告草稿");
    if (width < 900) await page.getByRole("button", { name: "关闭预览" }).click();
    await page.getByRole("link", { name: "维护待办", exact: true }).click();
    await page.getByRole("button", { name: "维护待办", exact: true }).waitFor();
    await page.getByRole("button", { name: "返回 Agent 会话", exact: true }).click();
    if (width < 900) await page.getByRole("button", { name: "打开文档预览" }).click();
    assert.equal(
      await page.getByLabel("文档正文", { exact: true }).inputValue(),
      "待保存的维护报告草稿",
    );
    await page.clock.fastForward(300);
    await page.screenshot({
      path: path.join(out, `agent-preview-${width}.png`),
      animations: "disabled",
    });
    await noOverflow();
    assert.deepEqual(errors, []);
    cases.push({
      width,
      height,
      standalone: true,
      state_preserved: true,
      agent_navigation_same_tab: true,
      agent_round_trip_drafts_preserved: true,
      edit_save: true,
      stop_resume_delete: true,
      agent_conversation_confirmation_resume_preview: true,
      flat_agent_surfaces: true,
      revoke_without_event: true,
    });
    await context.close();
  }
} finally {
  fs.writeFileSync(path.join(out, "report.json"), JSON.stringify(cases, null, 2));
  await browser.close();
}
console.log(JSON.stringify({ passed: true, cases: cases.length, output: out }));
