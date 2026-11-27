// Route keys are an allow-list, never server-provided executable URLs. Resource
// IDs come from permission-filtered projections; opaque task_ref is not an ID.
const ROUTES: Record<string, string> = {
  maintenance_agent: "/ai-workspace/agents/knowledge-maintenance",
  reviews: "/review",
  original_access: "/original-access",
  upload: "/upload",
  admin_ingest: "/admin/ingest",
  models: "/admin/weknora-models",
  knowledge: "/knowledge",
  knowledge_detail: "/knowledge/:id",
};

export function taskTarget({
  routeKey,
  resourceId,
  status,
  originalAccessBox = "mine",
}: {
  routeKey: string;
  resourceId?: string | null;
  status: string;
  originalAccessBox?: "inbox" | "mine";
}): string | null {
  const template = ROUTES[routeKey];
  if (!template || (template.includes(":id") && !resourceId)) return null;
  const route = template.replace(":id", encodeURIComponent(resourceId ?? ""));
  const query = new URLSearchParams();
  if (resourceId) query.set("target_id", resourceId);
  if (routeKey === "maintenance_agent") {
    if (!resourceId) query.set("view", "mine");
    query.set("mine", "true");
    if (status === "completed") query.set("status", "all");
  }
  if (routeKey === "original_access") query.set("box", originalAccessBox);
  if (routeKey === "reviews" && ["completed", "cancelled", "rejected"].includes(status)) {
    if (resourceId) query.set("queue", "completed");
    else return "/review/completed";
  }
  if (routeKey === "upload" && resourceId) {
    query.set("task_id", resourceId);
    if (
      ["completed", "cancelled", "rejected", "duplicate_skipped", "waiting_review"].includes(status)
    ) {
      query.set("view", "history");
    }
  }
  return query.size ? `${route}?${query}` : route;
}
