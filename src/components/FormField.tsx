import { cloneElement, useId, type ReactElement, type ReactNode } from "react";

// 统一表单行：label + 控件（children）+ 可选 hint / error。默认类不依赖任何业务页面；
// 尚未迁移的特殊表单仍可显式传 className。
interface FormFieldProps {
  label: ReactNode;
  children: ReactNode;
  error?: string | null;
  hint?: ReactNode;
  className?: string;
  required?: boolean;
}

export default function FormField({
  label,
  children,
  error,
  hint,
  className = "form-field",
  required = false,
}: FormFieldProps) {
  const fieldId = useId();
  // 仅当 children 是单一可接收 id 的元素时，注入 id 并以 htmlFor 关联；
  // 否则保留包裹式 label（包裹式 label 仍能与内部表单控件关联）。
  const isSingleElement = (value: ReactNode): value is ReactElement<{ id?: string }> =>
    value != null &&
    typeof value === "object" &&
    "props" in value &&
    typeof (value as ReactElement).props === "object";

  const control = isSingleElement(children)
    ? cloneElement(children, {
        id: (children as ReactElement<{ id?: string }>).props.id ?? fieldId,
      })
    : children;
  const labelFor = isSingleElement(children)
    ? ((children as ReactElement<{ id?: string }>).props.id ?? fieldId)
    : undefined;

  return (
    <label className={className} htmlFor={labelFor}>
      <span className="form-field-label">
        {label}
        {required && <span className="form-field-required"> *</span>}
      </span>
      {control}
      {hint && <small className="form-field-hint">{hint}</small>}
      {error && <span className="form-field-error">{error}</span>}
    </label>
  );
}
