import type { ButtonHTMLAttributes, ReactNode } from "react";

export type ButtonVariant = "primary" | "secondary" | "danger" | "ghost";
export type ButtonSize = "small" | "medium";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  icon?: ReactNode;
}

export default function Button({
  variant = "secondary",
  size = "medium",
  icon,
  className = "",
  children,
  type = "button",
  ...props
}: ButtonProps) {
  return (
    <button
      type={type}
      className={`product-button is-${variant} is-${size} ${className}`.trim()}
      {...props}
    >
      {icon && (
        <span className="product-button-icon" aria-hidden="true">
          {icon}
        </span>
      )}
      {children}
    </button>
  );
}
