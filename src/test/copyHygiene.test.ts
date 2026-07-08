import { describe, expect, it } from "vitest";

const sourceModules = import.meta.glob("../{pages,components,layouts}/**/*.{ts,tsx}", {
  eager: true,
  query: "?raw",
  import: "default",
}) as Record<string, string>;

const ordinaryUserFiles = [
  "pages/HomeDashboardPage.tsx",
  "pages/KnowledgeListPage.tsx",
  "pages/KnowledgeDetailPage.tsx",
  "pages/MyKnowledgePage.tsx",
  "pages/UploadPage.tsx",
  "pages/upload/UploadStepA.tsx",
  "pages/upload/UploadStepB.tsx",
  "pages/upload/UploadConfirmPanel.tsx",
  "pages/upload/UploadNamingCard.tsx",
  "pages/ProjectKnowledgePage.tsx",
  "pages/ProjectSettingsPage.tsx",
  "pages/ReviewPage.tsx",
  "pages/OriginalAccessPage.tsx",
  "components/WorkbuddyAccessCard.tsx",
  "components/ModelAdvancedSettings.tsx",
  "pages/knowledge/KnowledgeSearchBar.tsx",
  "pages/knowledge/KnowledgeCardList.tsx",
  "pages/knowledge/OpsInsightsPanel.tsx",
  "layouts/AppLayout.tsx",
  "components/IdentityMenu.tsx",
];

const bannedTerms = [
  "/api/v1",
  "真实后端",
  "后端服务已启动",
  "字段待后端",
  "路径 A",
  "路径A",
  "路径 B",
  "路径B",
  "WeKnora 召回",
  "权限网关",
  "fail-closed",
  "外部 LLM",
  "底座",
  "model_ref",
  "内部标识",
  "trace_id",
  "OAuth callback",
];

function visibleCopy(source: string): string {
  const withoutComments = source.replace(/\/\*[\s\S]*?\*\//g, "").replace(/\/\/.*$/gm, "");
  const snippets: string[] = [];

  for (const match of withoutComments.matchAll(/(["'`])((?:\\.|(?!\1)[\s\S])*?)\1/g)) {
    snippets.push(match[2]);
  }
  for (const match of withoutComments.matchAll(/>([^<>{}][^<>{}]*)</g)) {
    snippets.push(match[1]);
  }

  return snippets.join("\n");
}

describe("ordinary user copy hygiene", () => {
  it("keeps engineering acceptance wording out of ordinary user surfaces", () => {
    const violations: string[] = [];

    for (const file of ordinaryUserFiles) {
      const source = sourceModules[`../${file}`];
      expect(source, `${file} should be included in the copy hygiene scan`).toBeDefined();
      const copy = visibleCopy(source);
      for (const term of bannedTerms) {
        if (copy.includes(term)) violations.push(`${file}: ${term}`);
      }
    }

    expect(violations).toEqual([]);
  });
});
