import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from "react";

export type ButtonVariant = "primary" | "secondary" | "danger" | "ghost";
export type ButtonSize = "small" | "medium";

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ButtonVariant;
  size?: ButtonSize;
  icon?: ReactNode;
} & (
    | { iconOnly: true; "aria-label": string; icon: ReactNode; children?: never }
    | { iconOnly?: false; children?: ReactNode }
  );

const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  {
    variant = "secondary",
    size = "medium",
    icon,
    iconOnly = false,
    className = "",
    children,
    type = "button",
    ...props
  },
  ref,
) {
  return (
    <button
      type={type}
      ref={ref}
      className={`product-button is-${variant} is-${size} ${iconOnly ? "is-icon-only" : ""} ${className}`.trim()}
      title={props.title ?? (iconOnly ? props["aria-label"] : undefined)}
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
});

export default Button;
