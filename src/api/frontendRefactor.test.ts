import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { apiUpload, clearCsrfToken } from "./http";
import { createKnowledgeDirectory, fetchPreviewEntry, searchKnowledge } from "./knowledge";
import { fetchReview } from "./review";
import {
  decideMcpConsent,
  fetchMcpConsent,
  fetchMcpOAuthGrants,
  revokeMcpOAuthGrant,
} from "./mcpOAuth";
import { fetchPreviewText } from "./preview";

const fetcher = vi.fn<typeof fetch>();
beforeEach(() => {
  clearCsrfToken();
  fetcher
    .mockReset()
    .mockImplementation(
      async (url) =>
        new Response(
          String(url).endsWith("/auth/csrf") ? JSON.stringify({ csrf_token: "csrf-one" }) : "{}",
          { status: 200 },
        ),
    );
  vi.stubGlobal("fetch", fetcher);
});
afterEach(() => vi.unstubAllGlobals());

describe("shared multipart transport", () => {
  it("refreshes CSRF once while preserving the same bytes, metadata and abort signal", async () => {
    const body = new FormData();
    body.append("file", new File(["original bytes"], "sample.md"));
    body.append("session_id", "session-1");
    const signal = new AbortController().signal;
    let postCount = 0;
    let csrfCount = 0;
    fetcher.mockImplementation(async (url) => {
      if (String(url).endsWith("/csrf"))
        return new Response(JSON.stringify({ csrf_token: `csrf-${++csrfCount}` }));
      return ++postCount === 1
        ? new Response(JSON.stringify({ detail: { denied_reason: "csrf_token_mismatch" } }), {
            status: 403,
          })
        : new Response(JSON.stringify({ id: "uploaded" }));
    });
    await expect(apiUpload("/api/v1/ingest/upload", body, signal)).resolves.toEqual({
      id: "uploaded",
    });
    const posts = fetcher.mock.calls.filter(([, init]) => init?.method === "POST");
    expect(posts).toHaveLength(2);
    posts.forEach(([, init], index) => {
      expect(init).toMatchObject({ body, signal, credentials: "include" });
      expect(init?.headers).toEqual({ "X-CSRF-Token": `csrf-${index + 1}` });
      expect(new Headers(init?.headers).has("Content-Type")).toBe(false);
    });
    expect(body.get("session_id")).toBe("session-1");
  });

  it("does not retry a permission denial as a CSRF error", async () => {
    fetcher.mockImplementation(async (url) =>
      String(url).endsWith("/csrf")
        ? new Response(JSON.stringify({ csrf_token: "token" }))
        : new Response(JSON.stringify({ detail: { denied_reason: "permission_denied" } }), {
            status: 403,
          }),
    );
    await expect(apiUpload("/api/v1/ingest/upload", new FormData())).rejects.toMatchObject({
      status: 403,
    });
    expect(fetcher.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(1);
  });
});

describe("extracted domain adapters", () => {
  it("preserves the search abort signal through one CSRF refresh", async () => {
    const controller = new AbortController();
    let posts = 0;
    fetcher.mockImplementation(async (url, init) => {
      if (String(url).endsWith("/csrf"))
        return new Response(JSON.stringify({ csrf_token: "synthetic" }));
      if (++posts === 1)
        return new Response(JSON.stringify({ detail: { denied_reason: "csrf_token_mismatch" } }), {
          status: 403,
        });
      return new Promise((_resolve, reject) => {
        init?.signal?.addEventListener("abort", () =>
          reject(new DOMException("Aborted", "AbortError")),
        );
      });
    });
    const pending = searchKnowledge({ query: "synthetic", intent: "search" }, controller.signal);
    const rejected = expect(pending).rejects.toMatchObject({ name: "AbortError" });
    await vi.waitFor(() => expect(posts).toBe(2));
    controller.abort();
    await rejected;
    const requests = fetcher.mock.calls.filter(([, init]) => init?.method === "POST");
    expect(requests).toHaveLength(2);
    requests.forEach(([, init]) => expect(init?.signal).toBe(controller.signal));
  });

  it.each([503, 504])("does not retry search after HTTP %s", async (status) => {
    fetcher.mockImplementation(async (url) =>
      String(url).endsWith("/csrf")
        ? new Response(JSON.stringify({ csrf_token: "synthetic" }))
        : new Response(JSON.stringify({ detail: { denied_reason: "search_busy" } }), { status }),
    );
    await expect(searchKnowledge({ query: "synthetic", intent: "search" })).rejects.toMatchObject({
      status,
    });
    expect(fetcher.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(1);
  });

  it("loads a specific review with cookies without querying a list", async () => {
    await fetchReview("id/with space");
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(fetcher).toHaveBeenCalledWith(
      "/api/v1/reviews/id%2Fwith%20space",
      expect.objectContaining({ credentials: "include" }),
    );
  });

  it("posts the directory scope and parent without altering the body", async () => {
    const body = {
      scope: "project" as const,
      project_id: "project-1",
      parent_key: "root",
      display_name: "子目录",
    };
    await createKnowledgeDirectory(body);
    expect(fetcher).toHaveBeenCalledWith(
      "/api/v1/knowledge/directories",
      expect.objectContaining({ method: "POST", body: JSON.stringify(body) }),
    );
  });

  it("keeps OAuth consent and revocation paths and request payloads", async () => {
    await fetchMcpOAuthGrants();
    await fetchMcpConsent("request/id");
    await decideMcpConsent("request/id", { approved: true, operations: false });
    await revokeMcpOAuthGrant("grant/id");
    expect(fetcher).toHaveBeenCalledWith(
      "/api/v1/auth/mcp-oauth/grants",
      expect.objectContaining({ credentials: "include" }),
    );
    expect(fetcher).toHaveBeenCalledWith(
      "/api/v1/auth/mcp-oauth/requests/request%2Fid",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ approved: true, operations: false }),
      }),
    );
    expect(fetcher).toHaveBeenCalledWith(
      "/api/v1/auth/mcp-oauth/grants/grant%2Fid",
      expect.objectContaining({ method: "DELETE" }),
    );
  });

  it("rejects invalid preview entry URLs before sending credentials", async () => {
    for (const path of [
      "https://example.com/api/v1/preview/a",
      "/api/v1/preview/a/../../admin",
      "/api/v1/preview/a?next=x",
    ]) {
      await expect(fetchPreviewEntry(path)).rejects.toMatchObject({ status: 400 });
    }
    expect(fetcher).not.toHaveBeenCalled();
    await fetchPreviewEntry("/api/v1/preview/credential-1");
    expect(fetcher).toHaveBeenCalledWith(
      "/api/v1/preview/credential-1",
      expect.objectContaining({ credentials: "include" }),
    );
  });

  it("reads controlled preview text with its existing authenticated transport", async () => {
    fetcher.mockResolvedValueOnce(new Response("preview text"));
    await expect(fetchPreviewText("/api/v1/preview/id/file")).resolves.toBe("preview text");
    expect(fetcher).toHaveBeenCalledWith("/api/v1/preview/id/file", { credentials: "include" });
  });
});
