import type { ReviewActionResponseDTO } from "../types/review";

export type ReviewAction = "approve" | "reject" | "withdraw";

export interface ReviewActionFeedback {
  tone: "success" | "error" | "info";
  text: string;
}

export function reviewActionFeedback(
  result: ReviewActionResponseDTO,
  action: ReviewAction,
): ReviewActionFeedback {
  if (action === "approve") {
    if (result.status === "approval_failed") {
      return { tone: "error", text: "入库处理失败，审核尚未完成。请查看任务状态后重试。" };
    }
    if (result.status === "pending_reviewer") {
      return { tone: "info", text: "本次确认已记录，审核仍在等待其余确认。" };
    }
    if (result.status === "approving") {
      return { tone: "info", text: "确认已受理，入库仍在处理中。" };
    }
    if (result.status === "approved") {
      if (result.index_status === "indexing") {
        return { tone: "info", text: "审核已通过，索引仍在处理中；可检索状态请查看资料详情。" };
      }
      if (result.index_status && result.index_status !== "indexed") {
        return { tone: "info", text: "审核已通过，资料尚未完成检索索引；请查看资料详情。" };
      }
      return { tone: "success", text: "审核已通过。" };
    }
  }
  if (action === "reject" && result.status === "rejected") {
    return { tone: "success", text: "审核已拒绝。" };
  }
  if (action === "withdraw" && ["rejected", "cancelled", "withdrawn"].includes(result.status)) {
    return { tone: "success", text: "确认已撤回。" };
  }
  return { tone: "error", text: "操作结果尚未确认，请刷新后核对任务状态。" };
}
