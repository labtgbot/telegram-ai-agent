import type { ButtonHTMLAttributes, ReactNode } from "react";

type Variant = "primary" | "secondary" | "ghost" | "destructive";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  children: ReactNode;
}

const VARIANT_CLASSES: Record<Variant, string> = {
  primary: "bg-tg-button text-tg-button-text hover:opacity-90",
  secondary: "bg-tg-secondary-bg text-tg-text hover:opacity-90",
  ghost: "bg-transparent text-tg-link hover:underline",
  destructive: "bg-tg-destructive text-tg-button-text hover:opacity-90",
};

export function Button({
  variant = "primary",
  className = "",
  children,
  ...rest
}: ButtonProps): JSX.Element {
  const variantClass = VARIANT_CLASSES[variant];
  return (
    <button
      type="button"
      {...rest}
      className={`inline-flex items-center justify-center rounded-tg px-4 py-2 text-sm font-medium transition-opacity focus:outline-none focus:ring-2 focus:ring-tg-accent disabled:cursor-not-allowed disabled:opacity-50 ${variantClass} ${className}`.trim()}
    >
      {children}
    </button>
  );
}
