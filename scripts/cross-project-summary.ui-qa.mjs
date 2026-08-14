import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { chromium } from "playwright";

const base = process.env.UI_QA_BASE || "http://localhost:5179";
const outRoot = process.env.UI_QA_OUT_DIR || path.join(os.tmpdir(), "kap-ui-qa");
const outDir = path.join(outRoot, "cross-project-summary");
fs.mkdirSync(outDir, { recursive: true });

const alphaProject = "00000000-0000-0000-0000-000000000075";
const betaProject = "00000000-0000-0000-0000-000000000076";
const memberAsset = "00000000-0000-0000-0000-0000000000a1";
const crossAsset = "00000000-0000-0000-0000-0000000000a2";
const projectDirectoryKey = "project.deliverables";
const cases = [
  { name: "member-desktop", width: 1440, height: 1000, member: true },
  { name: "member-mobile", width: 390, height: 844, member: true },
  { name: "summary-desktop", width: 1280, height: 900 },
  { name: "summary-mobile", width: 390, height: 844 },
  { name: "empty-summary-mobile", width: 390, height: 844, empty: true },
  { name: "request-submitted-desktop", width: 1440, height: 1000, submit: true },
];

function access({ member = false, pending = false }) {
  return {
    discovery: true,
    summary: true,
    original: member,
    effective_source: member ? "project_member" : "system_rule",
    can_request_original: !member && !pending,
    cross_project_summary: !member,
    existing_request_status: pending ? "pending" : null,
    existing_grant_expires_at: null,
    can_delete: false,
    can_manage_lifecycle: false,
    can_retry_index: false,
  };
}

function listAsset(testCase) {
  const member = Boolean(testCase.member);
  return {
    id: member ? memberAsset : crossAsset,
    title: member ? "Alpha 项目供应链复盘" : "Beta 项目客户访谈洞察",
    canonical_name: member ? "【交付-复盘】供应链复盘_20260811_V1_L2" : null,
    scope: "project",
    zone: "asset",
    asset_type: "insight",
    confidentiality_level: member ? "L2" : "L3",
    ai_access_level: "A1",
    asset_status: "active",
    visibility: "project_only",
    tags: ["访谈", "洞察"],
    summary_text: testCase.empty
      ? null
      : member
        ? "项目成员可读取的本项目摘要。"
        : "（脱敏）仅包含可跨项目共享的访谈结论。",
    project_name: member ? "Alpha 项目" : "Beta 项目",
    lifecycle_phase: member ? "复盘" : null,
    confidence: null,
    last_called_at: null,
    updated_at: "2026-08-11T08:00:00Z",
    access_info: access({ member }),
    index_status: member ? "indexed" : null,
    weknora_parse_status: null,
    index_error_message: null,
    indexed_at: null,
  };
}

function detailAsset(testCase, pending) {
  const item = listAsset(testCase);
  return {
    ...item,
    project_id: testCase.member ? alphaProject : null,
    maintainer_name: testCase.member ? "项目维护人" : "王顾问",
    category_path: "项目资料 / 项目复盘",
    safe_version: "V3",
    retrieval_available: true,
    qa_available: false,
    summary: testCase.empty
      ? { one_liner: null, detailed: null, key_points: [] }
      : {
          one_liner: item.summary_text,
          detailed: testCase.member
            ? "项目成员可读取的本项目详细摘要。"
            : "（脱敏）安全摘要仅呈现可复用结论，不包含访谈原文、成员或内部标识。",
          key_points: [],
        },
    maintainer: testCase.member ? { id: "safe-member", name: "项目维护人" } : null,
    current_version: testCase.member
      ? { id: "safe-version", version_no: "v1", version_status: "active" }
      : null,
    canonical_markdown_status: testCase.member ? "generated" : null,
    access_info: access({ member: Boolean(testCase.member), pending }),
    archived_at: null,
    archive_reason: null,
    index_error_code: null,
  };
}

const browser = await chromium.launch({ args: ["--disable-gpu"] });
const results = [];

for (const testCase of cases) {
  let pending = false;
  let listedProjectId = null;
  let listedDirectoryKey = null;
  const context = await browser.newContext({
    viewport: { width: testCase.width, height: testCase.height },
  });
  await context.route("**/api/v1/**", async (route) => {
    const url = new URL(route.request().url());
    const fulfill = (body, status = 200) =>
      route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
    if (url.pathname === "/api/v1/auth/me") {
      return fulfill({
        user_id: "00000000-0000-0000-0000-000000000090",
        name: "跨项目摘要验收用户",
        email: "qa@example.test",
        status: "active",
        company_roles: ["consultant"],
        active_company_role: "consultant",
        is_business_user: true,
        can_discover_l5: false,
        project_memberships: [
          {
            project_id: alphaProject,
            project_name: "Alpha 项目",
            project_role: "consultant",
            status: "active",
          },
        ],
      });
    }
    if (url.pathname === "/api/v1/auth/csrf") return fulfill({ csrf_token: "ui-qa-csrf" });
    if (url.pathname === "/api/v1/knowledge/directories") {
      const rows = [
        {
          directory_key: projectDirectoryKey,
          name: "03 交付成果",
          description: "项目交付与复盘资料",
          scope: "project",
          display_path: "项目库 / Alpha 项目 / 03 交付成果",
          parent_key: null,
          project_id: alphaProject,
          project_name: "Alpha 项目",
        },
        {
          directory_key: projectDirectoryKey,
          name: "03 交付成果",
          description: "可跨项目发现的安全摘要",
          scope: "project",
          display_path: "项目库 / Beta 项目 / 03 交付成果",
          parent_key: null,
          project_id: betaProject,
          project_name: "Beta 项目",
        },
      ];
      const requestedScope = url.searchParams.get("scope");
      const requestedProject = url.searchParams.get("project_id");
      return fulfill({
        items: rows.filter(
          (row) =>
            (!requestedScope || row.scope === requestedScope) &&
            (!requestedProject || row.project_id === requestedProject),
        ),
      });
    }
    if (url.pathname === "/api/v1/knowledge") {
      listedProjectId = url.searchParams.get("project_id");
      listedDirectoryKey = url.searchParams.get("directory_key");
      return fulfill({
        items: [listAsset(testCase)],
        total: 1,
        page: 1,
        page_size: 20,
        has_next: false,
      });
    }
    if (url.pathname === `/api/v1/knowledge/${crossAsset}` && route.request().method() === "GET") {
      return fulfill(detailAsset(testCase, pending));
    }
    if (
      url.pathname === `/api/v1/knowledge/${crossAsset}/original-access/request` &&
      route.request().method() === "POST"
    ) {
      pending = true;
      return fulfill({ status: "created", request: null, grant: null, message: "已提交" });
    }
    return fulfill({ detail: { message: "UI QA route not configured" } }, 404);
  });

  const page = await context.newPage();
  await page.goto(`${base}/knowledge`, { waitUntil: "networkidle" });
  await page.getByRole("button", { name: /项目库/ }).click();
  await page
    .getByRole("button", { name: new RegExp(testCase.member ? "Alpha 项目" : "Beta 项目") })
    .click();
  await page.getByRole("button", { name: /03 交付成果/ }).click();
  if (testCase.member) {
    await page.getByText("可查看摘要与原文").waitFor();
  } else {
    await page.getByText("其他项目 · 摘要可见").waitFor();
    await page
      .getByRole("button", { name: `查看《${listAsset(testCase).title}》安全摘要` })
      .click();
    await page.getByRole("dialog").waitFor();
    await page.getByText("王顾问").waitFor();
    await page.getByText("项目资料 / 项目复盘").waitFor();
    if (testCase.empty) await page.getByText("暂无可共享摘要").last().waitFor();
    if (testCase.submit) {
      await page.getByRole("button", { name: "申请原文" }).click();
      await page.getByRole("dialog", { name: "申请原文" }).waitFor();
      await page.getByRole("button", { name: "提交申请" }).click();
      await page
        .getByText(/已提交原文访问申请/)
        .first()
        .waitFor();
      await page.getByRole("link", { name: "原文申请审批中" }).waitFor();
    }
  }
  await page.waitForTimeout(150);
  const metrics = await page.evaluate(() => {
    const text = document.body.innerText;
    return {
      overflowX: document.documentElement.scrollWidth - document.documentElement.clientWidth,
      overflowElements: [...document.querySelectorAll("body *")]
        .map((element) => ({
          selector: `${element.tagName.toLowerCase()}.${String(element.className).replaceAll(" ", ".")}`,
          right: Math.round(element.getBoundingClientRect().right),
          width: Math.round(element.getBoundingClientRect().width),
        }))
        .filter((item) => item.right > window.innerWidth + 2)
        .slice(0, 8),
      drawerOpen: Boolean(document.querySelector(".detail-drawer")),
      unsafeVisible: /storage_ref|source_file_ref|weknora|chunk|内部标识值|api[_ -]?key/i.test(
        text,
      ),
      projectWorkspaceLink: Boolean(
        document.querySelector('a[href*="/project/00000000-0000-0000-0000-000000000076"]'),
      ),
      safeCoreVisible:
        text.includes("核心信息") &&
        text.includes("王顾问") &&
        text.includes("问答不可用 · 检索可用"),
      text,
    };
  });
  await page.screenshot({
    path: path.join(outDir, `${testCase.name}.png`),
    fullPage: false,
    animations: "disabled",
  });
  results.push({
    name: testCase.name,
    width: testCase.width,
    overflowX: metrics.overflowX,
    overflowElements: metrics.overflowElements,
    drawerOpen: metrics.drawerOpen,
    unsafeVisible: metrics.unsafeVisible,
    projectWorkspaceLink: metrics.projectWorkspaceLink,
    directoryFlow:
      listedProjectId === (testCase.member ? alphaProject : betaProject) &&
      listedDirectoryKey === projectDirectoryKey,
    passed:
      metrics.overflowX <= 2 &&
      !metrics.unsafeVisible &&
      !metrics.projectWorkspaceLink &&
      listedProjectId === (testCase.member ? alphaProject : betaProject) &&
      listedDirectoryKey === projectDirectoryKey &&
      (testCase.member || (metrics.drawerOpen && metrics.safeCoreVisible)),
  });
  await context.close();
}

await browser.close();
fs.writeFileSync(path.join(outDir, "report.json"), JSON.stringify(results, null, 2));
console.log(JSON.stringify({ outDir, results }, null, 2));
if (results.some((result) => !result.passed)) process.exit(1);
