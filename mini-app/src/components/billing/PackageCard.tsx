import { Button } from "@/components/Button";
import type { PackageItem } from "@/types/billing";

interface PackageCardProps {
  pkg: PackageItem;
  isHighlighted?: boolean;
  isBuying?: boolean;
  disabled?: boolean;
  onBuy: (code: string) => void;
}

const NUMBER_FORMATTER = new Intl.NumberFormat("ru-RU");

export function PackageCard({
  pkg,
  isHighlighted = false,
  isBuying = false,
  disabled = false,
  onBuy,
}: PackageCardProps): JSX.Element {
  const borderClass = isHighlighted
    ? "border-tg-button"
    : "border-transparent hover:border-tg-separator";

  return (
    <article
      data-testid={`package-card-${pkg.code}`}
      className={`relative flex h-full flex-col gap-3 rounded-tg border-2 ${borderClass} bg-tg-section-bg p-4 shadow-tg transition-colors`}
    >
      {isHighlighted ? (
        <span
          className="absolute -top-2 right-3 rounded-full bg-tg-button px-2 py-0.5 text-xs font-semibold text-tg-button-text"
          data-testid={`package-badge-${pkg.code}`}
        >
          Популярный
        </span>
      ) : null}

      <header>
        <h3 className="text-base font-semibold text-tg-text">{pkg.title}</h3>
        <p className="mt-1 text-xs text-tg-hint">{pkg.description}</p>
      </header>

      <dl className="flex flex-1 flex-col gap-1 text-sm">
        <div className="flex items-baseline justify-between">
          <dt className="text-tg-hint">Токены</dt>
          <dd className="text-base font-semibold text-tg-text">
            {NUMBER_FORMATTER.format(pkg.tokens)}
          </dd>
        </div>
        <div className="flex items-baseline justify-between">
          <dt className="text-tg-hint">Цена</dt>
          <dd className="text-base font-semibold text-tg-text">
            {NUMBER_FORMATTER.format(pkg.stars)} ⭐
          </dd>
        </div>
        {pkg.is_subscription ? (
          <p className="mt-1 text-xs text-tg-accent">
            Подписка, продление каждые {pkg.subscription_days} дн.
          </p>
        ) : null}
      </dl>

      <Button
        onClick={() => onBuy(pkg.code)}
        disabled={disabled || isBuying}
        data-testid={`package-buy-${pkg.code}`}
      >
        {isBuying ? "Открываем…" : "Купить"}
      </Button>
    </article>
  );
}
