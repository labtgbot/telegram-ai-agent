import type { ReactElement } from "react";
import { AnimatedNumber } from "@/components/billing/AnimatedNumber";
import { Card } from "@/components/Card";
import type { Balance } from "@/types/billing";

interface BalanceCardProps {
  balance: Balance | undefined;
  isLoading: boolean;
  error: Error | null;
}

const PREMIUM_FORMATTER = new Intl.DateTimeFormat("ru-RU", {
  day: "2-digit",
  month: "long",
  year: "numeric",
});

function formatPremiumExpiry(value: string | null): string | null {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  return PREMIUM_FORMATTER.format(date);
}

export function BalanceCard({ balance, isLoading, error }: BalanceCardProps): ReactElement {
  if (error) {
    return (
      <Card title="Баланс">
        <p className="text-sm text-tg-destructive" data-testid="balance-error">
          Не удалось загрузить баланс: {error.message}
        </p>
      </Card>
    );
  }

  const tokens = balance?.token_balance ?? 0;
  const premiumUntil = formatPremiumExpiry(balance?.premium_expires_at ?? null);

  return (
    <Card title="Баланс" data-testid="balance-card">
      <div className="flex items-baseline gap-2">
        <AnimatedNumber
          value={tokens}
          className="text-4xl font-semibold text-tg-text"
          data-testid="balance"
        />
        <span className="text-base text-tg-hint">токенов</span>
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-2 text-sm">
        {balance?.is_premium ? (
          <span
            className="rounded-full bg-tg-accent/15 px-2 py-0.5 text-tg-accent"
            data-testid="premium-badge"
          >
            Premium{premiumUntil ? ` до ${premiumUntil}` : ""}
          </span>
        ) : null}
        {balance?.daily_bonus_available ? (
          <span
            className="rounded-full bg-tg-button/15 px-2 py-0.5 text-tg-button"
            data-testid="daily-bonus-badge"
          >
            Доступен ежедневный бонус
          </span>
        ) : null}
        {isLoading ? (
          <span className="text-tg-hint" data-testid="balance-loading">
            Обновляем…
          </span>
        ) : null}
      </div>
      <p className="mt-3 text-sm text-tg-hint">
        Покупайте токены за Telegram Stars и тратьте их на запросы к ИИ-агенту.
      </p>
    </Card>
  );
}
