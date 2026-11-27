import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { ActionConfirmation, ToolReceipts } from "./RunActions";
import type { WorkspaceAction } from "../../api/aiWorkspace";

const action: WorkspaceAction = {
  id: "receipt",
  run_id: "run",
  tool: "inspect_maintenance_issue",
  label: "核对问题与版本",
  status: "completed",
  summary: "已核对资料",
  created_at: "2026-11-27T01:00:00Z",
  updated_at: "2026-11-27T01:00:00Z",
  observation: {},
};
describe("Agent tool receipts", () => {
  it("renders business facts and scoped links while hiding implementation payloads", () => {
    const { container } = render(
      <MemoryRouter initialEntries={["/ai-workspace?session=conversation"]}>
        <ToolReceipts
          actions={[
            {
              ...action,
              observation: {
                receipt_summary: "已核对当前版本，发现两处电话信息。",
                title: "合成资料",
                issue_id: "private-identifier",
                raw_debug: "internal-debug-value",
                evidence: {
                  counts: { phone: 2 },
                  locations: [{ source: "summary", category: "phone", start: 10, end: 20 }],
                },
                url: "/ai-workspace/agents/knowledge-maintenance?library=company&tab=issues&asset_id=asset",
              },
            },
          ]}
        />
      </MemoryRouter>,
    );
    expect(screen.getByText("已核对当前版本，发现两处电话信息。")).toBeInTheDocument();
    fireEvent.click(screen.getByText("查看执行依据与结果"));
    expect(screen.getByText("2 处")).toBeInTheDocument();
    expect(screen.getByText("摘要")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "查看对应维护问题" })).toHaveAttribute(
      "href",
      expect.stringContaining("session=conversation"),
    );
    expect(container.textContent).not.toContain("private-identifier");
    expect(container.textContent).not.toContain("internal-debug-value");
    expect(container.querySelector("pre")).toBeNull();
  });

  it.each([
    {
      observation: { status: "not_executed", message: "资料版本已变化，请重新核对" },
      label: "未执行",
    },
    { observation: { error: "internal-model-error-must-not-be-rendered" }, label: "未能执行" },
  ])(
    "does not turn an unsuccessful $label invocation into a successful business action",
    ({ observation, label }) => {
      render(
        <MemoryRouter>
          <ToolReceipts
            actions={[
              {
                ...action,
                observation: {
                  ...observation,
                  url: "https://untrusted.example",
                },
              },
            ]}
          />
        </MemoryRouter>,
      );
      expect(screen.getByText(label, { selector: "span" })).toBeInTheDocument();
      expect(screen.queryByText("已执行")).not.toBeInTheDocument();
      expect(
        screen.queryByText("internal-model-error-must-not-be-rendered"),
      ).not.toBeInTheDocument();
      expect(screen.queryByRole("link")).not.toBeInTheDocument();
    },
  );

  it("confirms the human-readable exact operation without exposing internal identifiers", () => {
    const decide = vi.fn();
    render(
      <MemoryRouter>
        <ActionConfirmation
          action={{
            id: "action",
            tool: "recheck",
            label: "复检合成资料",
            summary: "复检当前资料，检查通过后关闭这一问题。",
            arguments: {
              issue_id: "hidden-issue",
              version_id: "hidden-version",
              policy_revision: 2,
            },
          }}
          busy={false}
          onDecision={decide}
        />
      </MemoryRouter>,
    );
    expect(screen.getByRole("region", { name: "确认本次操作" })).toHaveTextContent(
      "复检当前资料，检查通过后关闭这一问题。",
    );
    expect(screen.queryByText("hidden-version")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "拒绝本次操作" }));
    expect(decide).toHaveBeenCalledWith("reject");
  });
});
