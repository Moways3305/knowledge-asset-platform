import type { ReactNode } from "react";

export function ProductPage({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  return <div className={`product-page ${className}`.trim()}>{children}</div>;
}

export function PageHeader({
  title,
  description,
  actions,
  eyebrow,
}: {
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  eyebrow?: ReactNode;
}) {
  return (
    <header className="product-page-header">
      <div className="product-page-heading">
        {eyebrow && <div className="product-page-eyebrow">{eyebrow}</div>}
        <h2>{title}</h2>
        {description && <p>{description}</p>}
      </div>
      {actions && <div className="product-page-actions">{actions}</div>}
    </header>
  );
}

export function PageSection({
  title,
  description,
  actions,
  children,
  className = "",
}: {
  title?: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`product-section ${className}`.trim()}>
      {(title || description || actions) && (
        <div className="product-section-header">
          <div>
            {title && <h3>{title}</h3>}
            {description && <p>{description}</p>}
          </div>
          {actions && <div className="product-section-actions">{actions}</div>}
        </div>
      )}
      <div className="product-section-body">{children}</div>
    </section>
  );
}

export function PageToolbar({
  start,
  end,
  className = "",
}: {
  start?: ReactNode;
  end?: ReactNode;
  className?: string;
}) {
  return (
    <div className={`product-toolbar ${className}`.trim()}>
      <div className="product-toolbar-start">{start}</div>
      <div className="product-toolbar-end">{end}</div>
    </div>
  );
}

export interface StatusStripItem {
  label: ReactNode;
  value: ReactNode;
  tone?: "neutral" | "success" | "warning" | "danger";
}

export function StatusStrip({ items, label }: { items: StatusStripItem[]; label?: string }) {
  return (
    <div className="product-status-strip" aria-label={label}>
      {items.map((item, index) => (
        <div className={`product-status-item is-${item.tone ?? "neutral"}`} key={index}>
          <span className="product-status-value">{item.value}</span>
          <span className="product-status-label">{item.label}</span>
        </div>
      ))}
    </div>
  );
}

export function SettingsRow({
  title,
  description,
  control,
  disabledReason,
}: {
  title: ReactNode;
  description?: ReactNode;
  control: ReactNode;
  disabledReason?: ReactNode;
}) {
  return (
    <div className="product-setting-row">
      <div className="product-setting-copy">
        <strong>{title}</strong>
        {description && <span>{description}</span>}
        {disabledReason && <span className="product-setting-reason">{disabledReason}</span>}
      </div>
      <div className="product-setting-control">{control}</div>
    </div>
  );
}
