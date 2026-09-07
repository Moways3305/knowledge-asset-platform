import { afterEach, describe, expect, it, vi } from "vitest";
import { createUploadSession, replaceUploadSessionItemBytes } from "./ingest";

vi.mock("./http", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./http")>()),
  csrfHeaders: async () => ({}),
  withCsrfRetry: (request: () => Promise<unknown>) => request(),
}));

afterEach(() => vi.unstubAllGlobals());

describe("upload multipart modification dates", () => {
  it("preserves distinct dates for duplicate filenames in ordinal order", async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response("{}", { status: 200 }));
    vi.stubGlobal("fetch", fetcher);
    const files = [1, 7].map(
      (day) =>
        new File(["text"], "same.txt", {
          lastModified: new Date(2026, 8, day, 12).getTime(),
        }),
    );
    await createUploadSession({ files });
    const form = fetcher.mock.calls[0][1].body as FormData;
    expect(JSON.parse(String(form.get("client_formed_on")))).toEqual(["2026-09-01", "2026-09-07"]);
  });

  it("sends the newly selected file modification date with replacement bytes", async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response("{}", { status: 200 }));
    vi.stubGlobal("fetch", fetcher);
    await replaceUploadSessionItemBytes({
      sessionId: "s",
      itemId: "i",
      file: new File(["text"], "same.txt", { lastModified: new Date(2026, 8, 8, 12).getTime() }),
    });
    expect((fetcher.mock.calls[0][1].body as FormData).get("formed_on")).toBe("2026-09-08");
  });
});
