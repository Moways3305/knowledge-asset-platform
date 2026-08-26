import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import type { UploadDuplicateDTO } from "../../types/ingest";
import DuplicateComparisonPopover from "./DuplicateComparisonPopover";

const duplicate: UploadDuplicateDTO = {
  duplicate_state: "exact_content",
  match_type: "exact_content",
  match_count: 1,
  same_batch_group_id: null,
  same_batch_first_ordinal: null,
  default_selected: false,
  decision: null,
  preferred_candidate: {
    match_type: "exact_content",
    title: "已有资料",
    file_name: "existing.pdf",
    file_size: 1024,
    scope: "project",
    scope_label: "当前项目库",
    directory_key: "project.deliverables",
    subject: "交付方案",
    formed_on: "2026-08-01",
    version: "V1",
    asset_status: "active",
    ingested_at: "2026-08-02T00:00:00Z",
    safe_summary: "安全摘要",
    asset_id: "asset-1",
    can_view_detail: true,
    can_view_original: false,
    same_batch_ordinal: null,
  },
};

function view(value: UploadDuplicateDTO = duplicate) {
  const onSkip = vi.fn();
  const onIndependent = vi.fn();
  render(
    <MemoryRouter>
      <DuplicateComparisonPopover
        duplicate={value}
        current={{ fileName: "current.pdf", fileSize: 2048, scopeLabel: "当前项目库" }}
        onSkip={onSkip}
        onIndependent={onIndependent}
      />
    </MemoryRouter>,
  );
  return { onSkip, onIndependent };
}

describe("DuplicateComparisonPopover", () => {
  it("opens on hover and stays pinned after click until Escape", () => {
    view();
    const trigger = screen.getByRole("button", { name: "对比" });
    fireEvent.mouseEnter(trigger.parentElement!);
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    fireEvent.click(trigger);
    fireEvent.mouseLeave(trigger.parentElement!);
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });

  it("opens from keyboard focus and exposes both explicit decisions", () => {
    const handlers = view();
    const trigger = screen.getByRole("button", { name: "对比" });
    fireEvent.focus(trigger);
    fireEvent.click(screen.getByRole("button", { name: "本次不入库" }));
    fireEvent.click(screen.getByRole("button", { name: "仍作为独立资料入库" }));
    expect(handlers.onSkip).toHaveBeenCalledOnce();
    expect(handlers.onIndependent).toHaveBeenCalledOnce();
  });

  it("renders restricted matches without candidate facts or links", () => {
    view({
      ...duplicate,
      match_type: "restricted_match",
      match_count: null,
      preferred_candidate: {
        ...duplicate.preferred_candidate!,
        match_type: "restricted_match",
        title: null,
        asset_id: null,
        can_view_detail: false,
      },
    });
    fireEvent.click(screen.getByRole("button", { name: "对比" }));
    expect(screen.getByText(/详情受限/)).toBeInTheDocument();
    expect(screen.queryByText("已有资料")).not.toBeInTheDocument();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });

  it("lets a non-selected same-batch item become the retained item", () => {
    const onKeep = vi.fn();
    render(
      <MemoryRouter>
        <DuplicateComparisonPopover
          duplicate={{
            ...duplicate,
            duplicate_state: "same_batch",
            match_type: "same_batch",
            default_selected: false,
          }}
          current={{ fileName: "second.pdf" }}
          onKeep={onKeep}
        />
      </MemoryRouter>,
    );
    fireEvent.click(screen.getByRole("button", { name: "对比" }));
    fireEvent.click(screen.getByRole("button", { name: "设为本批保留项" }));
    expect(onKeep).toHaveBeenCalledOnce();
  });
});
