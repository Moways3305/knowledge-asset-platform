import { describe, expect, it } from "vitest";
import { ApiError, handleResponse } from "./http";

describe("handleResponse", () => {
  it("accepts a successful 204 response without trying to parse an empty body", async () => {
    await expect(
      handleResponse<void>(new Response(null, { status: 204 })),
    ).resolves.toBeUndefined();
  });

  it("turns FastAPI validation arrays into a safe actionable summary", async () => {
    const response = new Response(
      JSON.stringify({
        detail: [
          { loc: ["body", "manifest", 1, "file_size"], msg: "secret submitted input", input: "x" },
          { loc: ["body", "total_transport_batches"], msg: "another internal message" },
        ],
      }),
      { status: 422, headers: { "Content-Type": "application/json" } },
    );
    await expect(handleResponse(response)).rejects.toMatchObject({
      status: 422,
      deniedReason: "validation_error",
      message: "提交信息有误：请检查文件大小、批次计划后重试。",
      detail: { validation_fields: ["file_size", "total_transport_batches"] },
    } satisfies Partial<ApiError>);
  });
});
