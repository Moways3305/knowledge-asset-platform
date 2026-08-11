import type { ReactNode } from "react";
import { ArrowRight, Clock3 } from "lucide-react";
import { OPERATION_STATUS, type OperationStatus } from "./operationStatus";

export interface OperationCount {
  label: string;
  value: ReactNode;
  tone?: "neutral" | "success" | "warning" | "danger";
}

interface OperationStatusCardProps {
  status: OperationStatus;
  title: ReactNode;
  description?: ReactNode;
  counts?: OperationCount[];
  updatedAt?: ReactNode;
  nextStep?: ReactNode;
  actions?: ReactNode;
  compact?: boolean;
  live?: boolean;
}

export default function OperationStatusCard({
  status,
  title,
  description,
  counts = [],
  updatedAt,
  nextStep,
  actions,
  compact = false,
  live = false,
}: OperationStatusCardProps) {
  const definition = OPERATION_STATUS[status];
  const Icon = definition.Icon;
  return (
    <section
      className={`operation-status-card is-${definition.tone} ${compact ? "is-compact" : ""}`.trim()}
      data-operation-status={status}
      role={status === "failed" ? "alert" : "status"}
      aria-live={live ? "polite" : "off"}
    >
      <div className="operation-status-rail" aria-hidden="true" />
      <div className="operation-status-main">
        <div className="operation-status-heading">
          <span className="operation-status-icon" aria-hidden="true">
            <Icon className={status === "processing" ? "is-spinning" : ""} size={18} />
          </span>
          <div>
            <span className="operation-status-label">{definition.label}</span>
            <h3>{title}</h3>
            {description && <p>{description}</p>}
          </div>
          {updatedAt && (
            <span className="operation-status-updated">
              <Clock3 size={13} aria-hidden="true" />
              {updatedAt}
            </span>
          )}
        </div>
        {counts.length > 0 && (
          <dl className="operation-status-counts" aria-label="任务数量摘要">
            {counts.map((count) => (
              <div key={count.label} className={`is-${count.tone ?? "neutral"}`}>
                <dt>{count.label}</dt>
                <dd>{count.value}</dd>
              </div>
            ))}
          </dl>
        )}
        <div className="operation-status-footer">
          <span className="operation-status-next">
            <ArrowRight size={14} aria-hidden="true" />
            {nextStep ?? definition.guidance}
          </span>
          {actions && <div className="operation-status-actions">{actions}</div>}
        </div>
      </div>
    </section>
  );
}
