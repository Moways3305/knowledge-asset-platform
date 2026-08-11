import type { ReactNode } from "react";
import { Check } from "lucide-react";
import Button from "./Button";
import TaskModal from "./TaskModal";

export interface WizardStep {
  label: string;
  description?: string;
}

interface WizardModalProps {
  open: boolean;
  title: ReactNode;
  description?: ReactNode;
  steps: WizardStep[];
  currentStep: number;
  children: ReactNode;
  onBack: () => void;
  onNext: () => void;
  onCancel: () => void;
  onComplete: () => void;
  nextDisabled?: boolean;
  completeDisabled?: boolean;
  busy?: boolean;
  nextText?: string;
  completeText?: string;
  busyText?: string;
}

export default function WizardModal({
  open,
  title,
  description,
  steps,
  currentStep,
  children,
  onBack,
  onNext,
  onCancel,
  onComplete,
  nextDisabled = false,
  completeDisabled = false,
  busy = false,
  nextText = "继续",
  completeText = "完成",
  busyText = "正在提交…",
}: WizardModalProps) {
  const isLast = currentStep === steps.length - 1;
  return (
    <TaskModal
      open={open}
      title={title}
      description={description}
      onClose={onCancel}
      busy={busy}
      size="large"
      eyebrow={`第 ${currentStep + 1} 步，共 ${steps.length} 步`}
      footer={
        <>
          <Button onClick={onCancel} disabled={busy}>
            取消
          </Button>
          <span className="task-modal-footer-spacer" />
          {currentStep > 0 && (
            <Button onClick={onBack} disabled={busy}>
              返回
            </Button>
          )}
          <Button
            variant="primary"
            data-autofocus={isLast ? undefined : true}
            disabled={busy || (isLast ? completeDisabled : nextDisabled)}
            onClick={isLast ? onComplete : onNext}
          >
            {busy ? busyText : isLast ? completeText : nextText}
          </Button>
        </>
      }
    >
      <ol className="wizard-track" aria-label="任务步骤">
        {steps.map((step, index) => {
          const state =
            index < currentStep ? "complete" : index === currentStep ? "current" : "next";
          return (
            <li
              key={step.label}
              className={`is-${state}`}
              aria-current={state === "current" ? "step" : undefined}
            >
              <span className="wizard-step-marker" aria-hidden="true">
                {state === "complete" ? <Check size={13} /> : index + 1}
              </span>
              <span>
                <strong>{step.label}</strong>
                {step.description && <small>{step.description}</small>}
              </span>
            </li>
          );
        })}
      </ol>
      <div className="wizard-content">{children}</div>
    </TaskModal>
  );
}
