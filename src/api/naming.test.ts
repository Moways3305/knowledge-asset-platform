import { beforeEach, describe, expect, it, vi } from "vitest";

import { clearCsrfToken } from "./http";
import { previewBatchIngestNaming } from "./naming";

describe("previewBatchIngestNaming", () => {
  beforeEach(() => {
    clearCsrfToken();
    vi.restoreAllMocks();
  });

  it("serializes a complete project row without an inapplicable empty company field", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ csrf_token: "test-csrf" }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            items: [
              {
                task_id: "11111111-1111-4111-8111-111111111111",
                submittable: true,
                canonical_name:
                  "【ALPHA-26-2021-交付件】财务部战略行动计划及年度工作计划_20210116_V1_L2.txt",
                rule_version: 2,
                fields: {},
                notices: [],
                error_code: null,
                message: null,
              },
            ],
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      );

    const response = await previewBatchIngestNaming({
      targetScope: "project",
      targetProjectId: "22222222-2222-4222-8222-222222222222",
      items: [
        {
          taskId: "11111111-1111-4111-8111-111111111111",
          naming: {
            category_id: "33333333-3333-4333-8333-333333333333",
            subject: "财务部战略行动计划及年度工作计划",
            formed_on: "2021-01-16",
            version: "V1",
            applicable_to: "",
            confidentiality_level: "L2",
          },
        },
      ],
    });

    const request = fetchMock.mock.calls[1][1] as RequestInit;
    expect(JSON.parse(String(request.body))).toEqual({
      target_scope: "project",
      target_project_id: "22222222-2222-4222-8222-222222222222",
      items: [
        {
          task_id: "11111111-1111-4111-8111-111111111111",
          confidentiality_level: "L2",
          naming: {
            category_id: "33333333-3333-4333-8333-333333333333",
            subject: "财务部战略行动计划及年度工作计划",
            formed_on: "2021-01-16",
            version: "V1",
          },
        },
      ],
    });
    expect(response.items[0].submittable).toBe(true);
  });
});
