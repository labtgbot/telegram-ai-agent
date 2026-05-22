import * as React from "react";

import { cn } from "@/lib/utils";

type ButtonVariant = "primary" | "secondary" | "ghost" | "destructive";
type ButtonSize = "sm" | "md" | "lg";

const variantClasses: Record<ButtonVariant, string> = {
  primary:
    "bg-brand-600 text-white hover:bg-brand-700 focus-visible:outline focus-visible:outline-2 focus-visible:outline-brand-500 disabled:bg-brand-300",
  secondary:
    "bg-white text-slate-900 border border-slate-200 hover:bg-slate-50 disabled:opacity-60 dark:bg-slate-900 dark:text-slate-100 dark:border-slate-700 dark:hover:bg-slate-800",
  ghost:
    "bg-transparent text-slate-700 hover:bg-slate-100 disabled:opacity-60 dark:text-slate-200 dark:hover:bg-slate-800",
  destructive:
    "bg-red-600 text-white hover:bg-red-700 focus-visible:outline focus-visible:outline-2 focus-visible:outline-red-500 disabled:bg-red-300",
};

const sizeClasses: Record<ButtonSize, string> = {
  sm: "h-8 px-3 text-sm",
  md: "h-10 px-4 text-sm",
  lg: "h-12 px-6 text-base",
};

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { className, variant = "primary", size = "md", type = "button", ...props },
  ref,
) {
  return (
    <button
      ref={ref}
      type={type}
      className={cn(
        "inline-flex items-center justify-center rounded-md font-medium transition-colors disabled:pointer-events-none",
        variantClasses[variant],
        sizeClasses[size],
        className,
      )}
      {...props}
    />
  );
});
