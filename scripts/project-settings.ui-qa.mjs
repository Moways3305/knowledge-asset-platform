import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { chromium } from "playwright";

const base = process.env.UI_QA_BASE || "http://localhost:5179";
const outRoot = process.env.UI_QA_OUT_DIR || path.join(os.tmpdir(), "kap-ui-qa");
const outDir = path.join(outRoot, "project-settings");
fs.mkdirSync(outDir, { recursive: true });

const projectId = "00000000-0000-0000-0000-000000000074";
const otherProjectId = "00000000-0000-0000-0000-000000000075";

const scenarios = [
  { name: "manager-pending", role: "project_manager", canWrite: true, review: "pending" },
  { name: "member-readonly", role: "coach", canWrite: false, review: "forbidden" },
  { name: "manager-empty", role: "project_manager", canWrite: true, review: "empty" },
  { name: "review-error", role: "project_manager", canWrite: true, review: "error" },
  {
    name: "delete-ready",
    role: "project_manager",
    companyRole: "consultant",
    canWrite: true,
    review: "empty",
    deletion: {
      can_delete: true,
      asset_count: 0,
      member_count: 2,
      blockers: [],
    },
  },
  {
    name: "delete-blocked",
    role: "project_manager",
    companyRole: "consultant",
    canWrite: true,
    review: "empty",
    deletion: {
      can_delete: true,
      asset_count: 3,
      member_count: 2,
      blockers: ["project_has_assets"],
    },
  },
  {
    name: "delete-unauthorized",
    role: "consultant",
    companyRole: "boss",
    canWrite: false,
    review: "forbidden",
    deletion: {
      can_delete: false,
      asset_count: 0,
      member_count: 2,
      blockers: ["project_delete_forbidden"],
    },
  },
];
const viewports = [
  { name: "1440", width: 1440, height: 1000 },
  { name: "1280", width: 1280, height: 900 },
];

const settings = (canWrite, status = "active") => ({
  project_id: projectId,
  name: "客户交付体系优化",
  status,
  client_name: "客户运营中心",
  coach_name: "项目辅导老师",
  lifecycle_route_key: "route_A",
  lifecycle_phase_key: "诊断阶段",
  force_review_on_ingest: true,
  wecom_group_bound: true,
  wecom_group_label: "群组…9074",
  updated_at: "2026-07-15T08:00:00Z",
  can_write: canWrite,
});

const members = (canManage) => ({
  items: [
    {
      member_id: "00000000-0000-0000-0000-0000000000a1",
      user_id: "00000000-0000-0000-0000-0000000000b1",
      name: "项目负责人",
      email: "not-rendered-manager@example.test",
      company_roles: ["boss"],
      project_role: "project_manager",
      status: "active",
      source: "manual",
      joined_at: "2026-07-01T08:00:00Z",
      wecom_bound: false,
    },
    {
      member_id: "00000000-0000-0000-0000-0000000000a2",
      user_id: "00000000-0000-0000-0000-0000000000b2",
      name: "交付顾问",
      email: "not-rendered-consultant@example.test",
      company_roles: ["consulting_director"],
      project_role: "consultant",
      status: "active",
      source: "manual",
      joined_at: "2026-07-02T08:00:00Z",
      wecom_bound: true,
    },
  ],
  total: 2,
  can_manage: canManage,
});

const pendingReviews = [
  {
    id: "00000000-0000-0000-0000-0000000000c1",
    review_type: "project_ingest_approval",
    trigger_source: "upload",
    status: "pending_reviewer",
    target_asset_id: "00000000-0000-0000-0000-0000000000d1",
    asset_title: "客户访谈纪要",
    target_scope: "project",
    target_project_id: projectId,
    project_name: "客户交付体系优化",
    submitted_by: "00000000-0000-0000-0000-0000000000e1",
    reviewer_user_id: null,
    evidence_count: 0,
    review_comment: null,
    reviewed_at: null,
    created_at: "2026-07-15T09:00:00Z",
    can_decide: true,
    can_withdraw: false,
    general_manager_confirmation_status: null,
    consulting_director_confirmation_status: null,
  },
  {
    id: "00000000-0000-0000-0000-0000000000c2",
    review_type: "project_ingest_approval",
    trigger_source: "upload",
    status: "pending_reviewer",
    target_asset_id: null,
    asset_title: "其它项目记录不得出现",
    target_scope: "project",
    target_project_id: otherProjectId,
    project_name: "其它项目",
    submitted_by: null,
    reviewer_user_id: null,
    evidence_count: 0,
    review_comment: null,
    reviewed_at: null,
    created_at: null,
    can_decide: true,
    can_withdraw: false,
    general_manager_confirmation_status: null,
    consulting_director_confirmation_status: null,
  },
];

const browser = await chromium.launch({ args: ["--disable-gpu"] });
const results = [];

for (const scenario of scenarios) {
  for (const viewport of viewports) {
    const context = await browser.newContext({ viewport });
    await context.route("**/api/v1/**", async (route) => {
      const requestUrl = new URL(route.request().url());
      const fulfill = (body, status = 200) =>
        route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

      if (requestUrl.pathname === "/api/v1/auth/me") {
        const companyRole = scenario.companyRole ?? "consultant";
        return fulfill({
          user_id: "00000000-0000-0000-0000-000000000074",
          name: scenario.role === "project_manager" ? "项目经理验收用户" : "项目成员验收用户",
          email: "identity-not-shown@example.test",
          status: "active",
          company_roles: [companyRole],
          active_company_role: companyRole,
          is_business_user: true,
          can_discover_l5: false,
          project_memberships: scenario.role
            ? [
                {
                  project_id: projectId,
                  project_name: "客户交付体系优化",
                  project_role: scenario.role,
                  status: "active",
                },
              ]
            : [],
        });
      }
      if (requestUrl.pathname === `/api/v1/projects/${projectId}/settings`) {
        return fulfill(settings(scenario.canWrite, scenario.projectStatus));
      }
      if (requestUrl.pathname === `/api/v1/projects/${projectId}/members`) {
        return fulfill(members(scenario.role === "project_manager"));
      }
      if (requestUrl.pathname === `/api/v1/projects/${projectId}/candidate-members`) {
        return fulfill({
          items: [
            {
              user_id: "00000000-0000-0000-0000-0000000000b3",
              name: "候选辅导老师",
              email: "candidate-not-rendered@example.test",
            },
          ],
        });
      }
      if (requestUrl.pathname === `/api/v1/projects/${projectId}/deletion-readiness`) {
        return fulfill(
          scenario.deletion ?? {
            can_delete: false,
            asset_count: 2,
            member_count: 2,
            blockers: ["project_delete_forbidden", "project_has_assets"],
          },
        );
      }
      if (requestUrl.pathname === "/api/v1/reviews") {
        if (scenario.review === "error") {
          return fulfill({ detail: { message: "审核服务暂时不可用" } }, 503);
        }
        return fulfill({ items: scenario.review === "pending" ? pendingReviews : [], total: 0 });
      }
      return fulfill({ detail: { message: "UI QA route not configured" } }, 404);
    });

    const page = await context.newPage();
    await page.goto(`${base}/project/${projectId}/settings`, { waitUntil: "networkidle" });
    await page.getByRole("heading", { name: "客户交付体系优化" }).waitFor();

    if (scenario.review === "pending") {
      await page.getByText("客户访谈纪要").waitFor();
      if (await page.getByText("其它项目记录不得出现").count()) {
        throw new Error("cross-project review appeared in the queue");
      }
    } else if (scenario.review === "forbidden") {
      await page.getByText("当前身份无确认权限").waitFor();
    } else if (scenario.review === "empty") {
      await page.getByText("暂无待确认任务").waitFor();
    } else {
      await page.getByText("待确认任务加载失败").waitFor();
    }
    await page.bringToFront();
    await page.waitForTimeout(300);

    const metrics = await page.evaluate(() => {
      const root = document.documentElement;
      const rail = document.querySelector(".rail")?.getBoundingClientRect();
      const deck = document.querySelector(".deck")?.getBoundingClientRect();
      const layout = document.querySelector(".ps74-layout")?.getBoundingClientRect();
      const review = document.querySelector(".ps74-review-column")?.getBoundingClientRect();
      const collapse = document.querySelector(".rail-brand .rail-collapse");
      const bodyText = document.body.innerText;
      const deckText = document.querySelector(".deck")?.textContent ?? "";
      const clippedButtons = [...document.querySelectorAll("button, a.product-button")].filter(
        (element) => element.scrollWidth > element.clientWidth + 2,
      ).length;
      const deleteButton = [...document.querySelectorAll("button")].find(
        (element) => element.textContent?.trim() === "删除项目",
      );
      const memberSection = document
        .querySelector('[aria-labelledby="project-members-heading"]')
        ?.getBoundingClientRect();
      const memberActionRow = document
        .querySelector(".ps74-member-action-row")
        ?.getBoundingClientRect();
      const addMemberEntry = [...document.querySelectorAll("button")]
        .find((element) => element.textContent?.trim() === "添加成员")
        ?.getBoundingClientRect();
      const memberActionCell = document
        .querySelector(".ps74-member-actions")
        ?.getBoundingClientRect();
      const memberTableViewport = document
        .querySelector(".ps74-table-wrap")
        ?.getBoundingClientRect();
      const memberActionCellStyle = document.querySelector(".ps74-member-actions")
        ? getComputedStyle(document.querySelector(".ps74-member-actions"))
        : null;
      const memberActionControls = document
        .querySelector(".ps74-member-action-controls")
        ?.getBoundingClientRect();
      const memberRow = document
        .querySelector(".ps74-members-table tbody tr")
        ?.getBoundingClientRect();
      const actionRowStyle = document.querySelector(".ps74-member-action-row")
        ? getComputedStyle(document.querySelector(".ps74-member-action-row"))
        : null;
      const memberActionButtonsClipped = [
        ...document.querySelectorAll(".ps74-member-action-controls button"),
      ].filter(
        (element) =>
          element.scrollWidth > element.clientWidth + 2 ||
          element.scrollHeight > element.clientHeight + 2,
      ).length;
      return {
        overflowX: root.scrollWidth - root.clientWidth,
        shellOverlap: rail && deck ? Math.max(0, rail.right - deck.left) : 1,
        reviewOutsideLayout:
          layout && review ? review.left < layout.left || review.right > layout.right + 1 : true,
        collapseInsideBrand: Boolean(collapse),
        collapseName: collapse?.getAttribute("aria-label") ?? "",
        moduleTitle: document.querySelector(".deck-title")?.textContent?.trim() ?? "",
        internalIdentityVisible:
          bodyText.includes("example.test") ||
          bodyText.includes("00000000-0000-0000-0000-000000000074"),
        uncontractedHeaderAction: /搜索|导出|新建项目|通知/.test(deckText),
        clippedButtons,
        lifecycleGateCount: document.querySelectorAll(".ps74-lifecycle-gates > div").length,
        deleteButtonVisible: Boolean(deleteButton),
        deleteBlockerVisible: Boolean(document.querySelector(".ps74-delete-blocker")),
        dangerZoneVisible: Boolean(document.querySelector(".ps74-danger-zone")),
        memberEntryCenterDelta:
          memberSection && addMemberEntry
            ? Math.abs(
                addMemberEntry.left +
                  addMemberEntry.width / 2 -
                  (memberSection.left + memberSection.width / 2),
              )
            : null,
        memberActionRowCentered:
          memberSection && memberActionRow
            ? Math.abs(
                memberActionRow.left +
                  memberActionRow.width / 2 -
                  (memberSection.left + memberSection.width / 2),
              ) <= 2
            : false,
        memberDividerVisible:
          Boolean(actionRowStyle) &&
          Number.parseFloat(actionRowStyle.borderTopWidth) >= 1 &&
          actionRowStyle.borderTopStyle !== "none" &&
          actionRowStyle.borderTopColor !== "rgba(0, 0, 0, 0)",
        memberActionColumnWaste:
          memberActionCell && memberActionControls && memberActionCellStyle
            ? memberActionCell.width -
              memberActionControls.width -
              Number.parseFloat(memberActionCellStyle.paddingLeft) -
              Number.parseFloat(memberActionCellStyle.paddingRight) -
              Number.parseFloat(memberActionCellStyle.borderLeftWidth) -
              Number.parseFloat(memberActionCellStyle.borderRightWidth)
            : null,
        memberRowHeight: memberRow?.height ?? null,
        memberActionButtonsClipped,
        memberActionColumnFullyVisible:
          memberTableViewport && memberActionCell && memberActionControls
            ? memberActionCell.left >= memberTableViewport.left - 1 &&
              memberActionCell.right <= memberTableViewport.right + 1 &&
              memberActionControls.left >= memberTableViewport.left - 1 &&
              memberActionControls.right <= memberTableViewport.right + 1
            : false,
      };
    });

    await page.screenshot({
      path: path.join(outDir, `${scenario.name}-${viewport.name}.png`),
      fullPage: false,
      animations: "disabled",
    });
    let deletionEvidence = {};
    let memberActionEvidence = {};
    if (scenario.name === "manager-pending") {
      const memberSection = page.locator('[aria-labelledby="project-members-heading"]');
      await memberSection.scrollIntoViewIfNeeded();
      await memberSection.screenshot({
        path: path.join(outDir, `${scenario.name}-member-action-collapsed-${viewport.name}.png`),
        animations: "disabled",
      });
      await page.getByRole("button", { name: "添加成员" }).click();
      const addMemberForm = page.locator(".ps74-add-member-form");
      await addMemberForm.waitFor();
      await memberSection.screenshot({
        path: path.join(outDir, `${scenario.name}-member-action-expanded-${viewport.name}.png`),
        animations: "disabled",
      });
      memberActionEvidence = await page.evaluate(() => {
        const section = document
          .querySelector('[aria-labelledby="project-members-heading"]')
          ?.getBoundingClientRect();
        const form = document.querySelector(".ps74-add-member-form")?.getBoundingClientRect();
        const confirm = [...document.querySelectorAll("button")].find(
          (element) => element.textContent?.trim() === "确认添加",
        );
        const cancel = [...document.querySelectorAll("button")].find(
          (element) => element.textContent?.trim() === "取消",
        );
        return {
          memberFormCenterDelta:
            section && form
              ? Math.abs(form.left + form.width / 2 - (section.left + section.width / 2))
              : null,
          memberFormActionsReachable:
            Boolean(confirm && cancel) &&
            confirm.getBoundingClientRect().width > 0 &&
            cancel.getBoundingClientRect().width > 0,
        };
      });
      await page.getByRole("button", { name: "取消" }).click();
      await page.getByRole("button", { name: "添加成员" }).waitFor();
      memberActionEvidence.memberEntryRestoredAfterCancel = true;
    }
    if (scenario.name === "delete-ready") {
      const deleteButton = page.getByRole("button", { name: "删除项目" });
      await deleteButton.click();
      const dialog = page.getByRole("dialog", { name: /删除项目“客户交付体系优化”/ });
      await dialog.waitFor();
      await page.screenshot({
        path: path.join(outDir, `${scenario.name}-confirmation-${viewport.name}.png`),
        fullPage: false,
        animations: "disabled",
      });
      deletionEvidence = {
        deleteConfirmationVisible: await dialog.isVisible(),
        irreversibleCopyVisible: (await dialog.textContent()).includes("不可恢复"),
        memberRemovalCopyVisible: (await dialog.textContent()).includes("2 条项目成员关系"),
        confirmInitiallyDisabled: await dialog
          .getByRole("button", { name: "删除项目" })
          .isDisabled(),
      };
      await dialog.getByRole("button", { name: "取消" }).click();
    }
    let collapsedMetrics = {};
    if (scenario.name === "manager-pending" && viewport.name === "1440") {
      await page.getByRole("button", { name: "折叠主导航" }).click();
      await page.waitForTimeout(220);
      collapsedMetrics = await page.evaluate(() => {
        const rail = document.querySelector(".rail")?.getBoundingClientRect();
        const button = document.querySelector(".rail-collapse")?.getBoundingClientRect();
        const projectLink = document.querySelector('a[aria-label="项目设置"]');
        return {
          collapsedBoundaryOffset:
            rail && button ? Math.abs(button.left + button.width / 2 - rail.right) : 999,
          collapsedButtonName:
            document.querySelector(".rail-collapse")?.getAttribute("aria-label") ?? "",
          collapsedProjectTooltip: projectLink?.getAttribute("title") ?? "",
        };
      });
    }
    results.push({
      scenario: scenario.name,
      viewport: viewport.name,
      ...metrics,
      ...memberActionEvidence,
      ...deletionEvidence,
      ...collapsedMetrics,
    });
    await context.close();
  }
}

await browser.close();
for (const result of results) {
  result.pass = !(
    result.overflowX > 2 ||
    result.shellOverlap > 1 ||
    result.reviewOutsideLayout ||
    !result.collapseInsideBrand ||
    result.collapseName !== "折叠主导航" ||
    result.moduleTitle !== "项目设置" ||
    result.internalIdentityVisible ||
    result.uncontractedHeaderAction ||
    (typeof result.collapsedBoundaryOffset === "number" &&
      (result.collapsedBoundaryOffset > 2 ||
        result.collapsedButtonName !== "展开主导航" ||
        result.collapsedProjectTooltip !== "项目设置")) ||
    result.clippedButtons > 0 ||
    result.lifecycleGateCount !== 0 ||
    (result.scenario === "delete-ready" && !result.deleteButtonVisible) ||
    (result.scenario === "manager-pending" &&
      (result.memberEntryCenterDelta === null ||
        result.memberEntryCenterDelta > 2 ||
        !result.memberActionRowCentered ||
        !result.memberDividerVisible ||
        result.memberActionColumnWaste === null ||
        // Chromium table-width rounding differs between local Windows and CI Linux.
        // A 24px residual is still smaller than a control gap and does not create a blank column.
        result.memberActionColumnWaste > 24 ||
        result.memberRowHeight === null ||
        result.memberRowHeight > 64 ||
        result.memberActionButtonsClipped > 0 ||
        !result.memberActionColumnFullyVisible ||
        result.memberFormCenterDelta === null ||
        result.memberFormCenterDelta > 2 ||
        !result.memberFormActionsReachable ||
        !result.memberEntryRestoredAfterCancel)) ||
    (result.scenario === "delete-blocked" &&
      (!result.deleteBlockerVisible || result.deleteButtonVisible || !result.dangerZoneVisible)) ||
    (result.scenario === "delete-unauthorized" && result.dangerZoneVisible) ||
    (result.scenario === "delete-ready" &&
      (!result.deleteConfirmationVisible ||
        !result.irreversibleCopyVisible ||
        !result.memberRemovalCopyVisible ||
        !result.confirmInitiallyDisabled))
  );
}
fs.writeFileSync(path.join(outDir, "report.json"), JSON.stringify(results, null, 2));
console.log(JSON.stringify({ outDir, results }, null, 2));

if (results.some((result) => !result.pass)) {
  process.exit(1);
}
