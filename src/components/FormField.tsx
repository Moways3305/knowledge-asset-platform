import type { ReactNode } from "react";

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
  return (
    <label className={className}>
      <span className="form-field-label">
        {label}
        {required && <span className="form-field-required"> *</span>}
      </span>
      {children}
      {hint && <small className="form-field-hint">{hint}</small>}
      {error && <span className="form-field-error">{error}</span>}
    </label>
  );
}
