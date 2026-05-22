import type { ReactElement, HTMLAttributes, ReactNode } from "react";

interface CardProps extends HTMLAttributes<HTMLDivElement> {
  title?: string;
  children: ReactNode;
}

export function Card({ title, children, className = "", ...rest }: CardProps): ReactElement {
  return (
    <section {...rest} className={`rounded-tg bg-tg-section-bg p-4 shadow-tg ${className}`.trim()}>
      {title ? (
        <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-tg-section-header">
          {title}
        </h2>
      ) : null}
      {children}
    </section>
  );
}
