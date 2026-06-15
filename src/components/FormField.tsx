import type { ReactNode } from "react";

// 统一表单行：label + 控件（children）+ 可选 hint / error。className 默认复用现有
// `.kl-modal-field`（label>span + input/select 的既有样式），故在模态表单里是直接替换；
// 其它场景可传入相应的既有 field 类名。error / hint 用既有 CSS 变量着色。
interface FormFieldProps {
  label: ReactNode;
  children: ReactNode;
  error?: string | null;
  hint?: ReactNode;
  className?: string;
}

export default function FormField({
  label,
  children,
  error,
  hint,
  className = "kl-modal-field",
}: FormFieldProps) {
  return (
    <label className={className}>
      <span>{label}</span>
      {children}
      {hint && <small className="form-field-hint">{hint}</small>}
      {error && <span className="form-field-error">{error}</span>}
    </label>
  );
}
