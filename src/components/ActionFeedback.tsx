import type { ReactNode } from "react";
import { CheckCircle2, Clock3, Info, TriangleAlert, XCircle } from "lucide-react";

export type ActionFeedbackState =
  | "submitted"
  | "processing"
  | "success"
  | "partial"
  | "error"
  | "info";

interface ActionFeedbackProps {
  state: ActionFeedbackState;
  title: ReactNode;
  description?: ReactNode;
  action?: ReactNode;
  nextStep?: ReactNode;
  updatedAt?: ReactNode;
}

const iconByState = {
  submitted: Clock3,
  processing: Clock3,
  success: CheckCircle2,
  partial: TriangleAlert,
  error: XCircle,
  info: Info,
};

export default function ActionFeedback({
  state,
  title,
  description,
  action,
  nextStep,
  updatedAt,
}: ActionFeedbackProps) {
  const Icon = iconByState[state];
  return (
    <div
      className={`action-feedback is-${state}`}
      role={state === "error" ? "alert" : "status"}
      aria-live="polite"
      data-feedback-state={state}
    >
      <Icon size={17} aria-hidden="true" />
      <span>
        <strong>{title}</strong>
        {description && <small>{description}</small>}
        {nextStep && <small className="action-feedback-next">下一步：{nextStep}</small>}
        {updatedAt && <small className="action-feedback-updated">更新于 {updatedAt}</small>}
      </span>
      {action && <div className="action-feedback-action">{action}</div>}
    </div>
  );
}
