import * as React from "react";

import { cn } from "@/lib/utils";

export type InputProps = React.InputHTMLAttributes<HTMLInputElement>;

export const Input = React.forwardRef<HTMLInputElement, InputProps>(function Input(
  { className, type = "text", ...props },
  ref,
) {
  return (
    <input
      ref={ref}
      type={type}
      className={cn(
        "h-10 w-full rounded-md border border-slate-200 bg-white px-3 text-sm text-slate-900 shadow-sm",
        "placeholder:text-slate-400 focus-visible:outline focus-visible:outline-2 focus-visible:outline-brand-500",
        "disabled:cursor-not-allowed disabled:opacity-60",
        "dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100 dark:placeholder:text-slate-500",
        className,
      )}
      {...props}
    />
  );
});
