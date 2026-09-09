import type { KnowledgeDetailVM } from "../types/knowledge";

export function summaryPendingLabel(asset: KnowledgeDetailVM): string {
  const safePending =
    asset.summaryStatus === "safe_pending" ||
    (!asset.summaryStatus && ["L2", "L3", "L4"].includes(asset.confidentialityLevel));
  return safePending ? "安全摘要待处理" : "摘要待生成";
}
