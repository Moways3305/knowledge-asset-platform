import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import DetailDrawer from "./DetailDrawer";
import OperationStatusCard from "./OperationStatusCard";
import TaskModal from "./TaskModal";
import WizardModal from "./WizardModal";
import type { OperationStatus } from "./operationStatus";

describe("experience system", () => {
  it("gives every operation state one consistent semantic label", () => {
    const states: OperationStatus[] = [
      "not_started",
      "queued",
      "processing",
      "awaiting_confirmation",
      "completed",
      "partial",
      "failed",
      "attention",
    ];
    const { rerender } = render(
      <OperationStatusCard status={states[0]} title="导入任务" nextStep="下一步" />,
    );
    states.forEach((status) => {
      rerender(<OperationStatusCard status={status} title="导入任务" nextStep="下一步" />);
      expect(screen.getByText("导入任务").closest("section")).toHaveAttribute(
        "data-operation-status",
        status,
      );
    });
  });

  it("traps focus, closes on Escape, and restores the trigger", async () => {
    const onClose = vi.fn();
    function Harness() {
      const [open, setOpen] = useState(false);
      return (
        <>
          <button onClick={() => setOpen(true)}>打开任务</button>
          <TaskModal
            open={open}
            title="核对任务"
            onClose={() => {
              onClose();
              setOpen(false);
            }}
            footer={<button data-autofocus>保存</button>}
          >
            <button>第一项</button>
          </TaskModal>
        </>
      );
    }
    render(<Harness />);
    const trigger = screen.getByRole("button", { name: "打开任务" });
    trigger.focus();
    fireEvent.click(trigger);

    await waitFor(() => expect(screen.getByRole("button", { name: "保存" })).toHaveFocus());
    fireEvent.keyDown(screen.getByRole("dialog"), { key: "Tab" });
    expect(screen.getByRole("button", { name: "关闭弹窗" })).toHaveFocus();
    fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("button", { name: "打开任务" })).toHaveFocus();
  });

  it("keeps wizard review separate from the final write", () => {
    const complete = vi.fn();
    function Harness() {
      const [step, setStep] = useState(0);
      return (
        <WizardModal
          open
          title="迁移知识库"
          steps={[{ label: "选择模型" }, { label: "确认影响" }]}
          currentStep={step}
          onBack={() => setStep(0)}
          onNext={() => setStep(1)}
          onCancel={() => {}}
          onComplete={complete}
          completeText="提交迁移作业"
        >
          <p>{step === 0 ? "本地核对" : "异步提交说明"}</p>
        </WizardModal>
      );
    }
    render(<Harness />);
    fireEvent.click(screen.getByRole("button", { name: "继续" }));
    expect(complete).not.toHaveBeenCalled();
    expect(screen.getByText("异步提交说明")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "提交迁移作业" }));
    expect(complete).toHaveBeenCalledTimes(1);
  });

  it("renders a modal detail drawer without exposing hidden identifiers", () => {
    render(
      <DetailDrawer open title="作业详情" onClose={() => {}}>
        <OperationStatusCard
          status="processing"
          title="批量索引"
          counts={[{ label: "总计", value: 12 }]}
        />
      </DetailDrawer>,
    );
    expect(screen.getByRole("dialog", { name: "作业详情" })).toBeInTheDocument();
    expect(screen.getByText("处理中")).toBeInTheDocument();
    expect(screen.queryByText(/job_id|trace_id|scope_filter/i)).not.toBeInTheDocument();
  });
});
