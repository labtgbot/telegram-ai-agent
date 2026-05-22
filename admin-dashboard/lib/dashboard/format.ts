/**
 * Number / currency / date formatters used by the dashboard.
 *
 * Locale is fixed to `en-US` so server-rendered output matches the client
 * hydration without depending on the visitor's locale (the rest of the admin
 * panel is English-only).
 */

const LOCALE = "en-US";

const compactNumber = new Intl.NumberFormat(LOCALE, {
  notation: "compact",
  maximumFractionDigits: 1,
});

const integerNumber = new Intl.NumberFormat(LOCALE, {
  maximumFractionDigits: 0,
});

const usd = new Intl.NumberFormat(LOCALE, {
  style: "currency",
  currency: "USD",
  maximumFractionDigits: 0,
});

const usdPrecise = new Intl.NumberFormat(LOCALE, {
  style: "currency",
  currency: "USD",
  maximumFractionDigits: 2,
});

const percent = new Intl.NumberFormat(LOCALE, {
  style: "decimal",
  minimumFractionDigits: 1,
  maximumFractionDigits: 1,
});

const dateShort = new Intl.DateTimeFormat(LOCALE, {
  month: "short",
  day: "2-digit",
  timeZone: "UTC",
});

const dateTime = new Intl.DateTimeFormat(LOCALE, {
  month: "short",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  timeZone: "UTC",
});

export function formatNumberCompact(value: number): string {
  return compactNumber.format(value);
}

export function formatInteger(value: number): string {
  return integerNumber.format(Math.round(value));
}

export function formatUsd(value: number, opts: { precise?: boolean } = {}): string {
  return (opts.precise ? usdPrecise : usd).format(value);
}

/** Render percent values that already are in percentage units (0-100). */
export function formatPercent(value: number, opts: { sign?: boolean } = {}): string {
  const formatted = `${percent.format(value)}%`;
  if (!opts.sign || value === 0) return formatted;
  return value > 0 ? `+${formatted}` : formatted;
}

export function formatStars(value: number): string {
  return `${integerNumber.format(value)} ⭐`;
}

export function formatDateShort(iso: string): string {
  return dateShort.format(new Date(iso));
}

export function formatDateTime(iso: string): string {
  return dateTime.format(new Date(iso));
}

/** "5m ago", "2h ago", … — useful for live-ish lists. */
export function formatRelative(iso: string, now: Date = new Date()): string {
  const then = new Date(iso).getTime();
  const seconds = Math.max(0, Math.round((now.getTime() - then) / 1000));
  if (seconds < 60) return "just now";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  if (days < 30) return `${days}d ago`;
  const months = Math.round(days / 30);
  return `${months}mo ago`;
}

export function deltaTone(value: number): "up" | "down" | "flat" {
  if (value > 0.1) return "up";
  if (value < -0.1) return "down";
  return "flat";
}
