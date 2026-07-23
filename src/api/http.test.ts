import { describe, expect, it } from "vitest";
import { handleResponse } from "./http";

describe("handleResponse", () => {
  it("accepts a successful 204 response without trying to parse an empty body", async () => {
    await expect(
      handleResponse<void>(new Response(null, { status: 204 })),
    ).resolves.toBeUndefined();
  });
});
