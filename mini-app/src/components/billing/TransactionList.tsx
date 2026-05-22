import { Button } from "@/components/Button";
import { Card } from "@/components/Card";
import type { TransactionItem, TransactionType, TransactionsResponse } from "@/types/billing";

interface TransactionListProps {
  data: TransactionsResponse | undefined;
  isLoading: boolean;
  error: Error | null;
  page: number;
  filter: TransactionType | null;
  onPageChange: (page: number) => void;
  onFilterChange: (filter: TransactionType | null) => void;
}

interface FilterOption {
  value: TransactionType | null;
  label: string;
}

const FILTERS: readonly FilterOption[] = [
  { value: null, label: "Все" },
  { value: "purchase", label: "Покупки" },
  { value: "spend", label: "Списания" },
  { value: "bonus", label: "Бонусы" },
  { value: "refund", label: "Возвраты" },
] as const;

const DATE_FORMATTER = new Intl.DateTimeFormat("ru-RU", {
  day: "2-digit",
  month: "short",
  hour: "2-digit",
  minute: "2-digit",
});

const NUMBER_FORMATTER = new Intl.NumberFormat("ru-RU", { signDisplay: "always" });

function formatTimestamp(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return DATE_FORMATTER.format(date);
}

const TYPE_LABEL: Record<TransactionType, string> = {
  purchase: "Покупка",
  spend: "Списание",
  bonus: "Бонус",
  refund: "Возврат",
  manual_bonus: "Ручной бонус",
};

function describe(tx: TransactionItem): string {
  const base = TYPE_LABEL[tx.transaction_type] ?? tx.transaction_type;
  if (tx.package_name) return `${base} · ${tx.package_name}`;
  return base;
}

function tokenDelta(tx: TransactionItem): number {
  if (tx.transaction_type === "spend") return -Math.abs(tx.tokens_amount);
  return Math.abs(tx.tokens_amount);
}

export function TransactionList({
  data,
  isLoading,
  error,
  page,
  filter,
  onPageChange,
  onFilterChange,
}: TransactionListProps): JSX.Element {
  return (
    <Card title="История операций">
      <div className="mb-3 flex flex-wrap gap-2" data-testid="transactions-filter">
        {FILTERS.map((opt) => {
          const isActive = filter === opt.value;
          return (
            <button
              type="button"
              key={opt.value ?? "all"}
              onClick={() => onFilterChange(opt.value)}
              data-testid={`tx-filter-${opt.value ?? "all"}`}
              data-active={isActive}
              className={`rounded-tg px-3 py-1 text-xs font-medium transition-colors ${
                isActive
                  ? "bg-tg-button text-tg-button-text"
                  : "bg-tg-secondary-bg text-tg-text hover:opacity-90"
              }`}
            >
              {opt.label}
            </button>
          );
        })}
      </div>

      {error ? (
        <p className="text-sm text-tg-destructive" data-testid="transactions-error">
          Не удалось загрузить историю: {error.message}
        </p>
      ) : null}

      {data && data.items.length === 0 && !error ? (
        <p className="text-sm text-tg-hint" data-testid="transactions-empty">
          Здесь будут отображаться операции.
        </p>
      ) : null}

      {data && data.items.length > 0 ? (
        <ul className="divide-y divide-tg-separator" data-testid="transactions">
          {data.items.map((tx) => {
            const delta = tokenDelta(tx);
            const isNegative = delta < 0;
            return (
              <li
                key={tx.id}
                className="flex items-center justify-between gap-3 py-2"
                data-testid={`tx-${tx.id}`}
              >
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium text-tg-text">{describe(tx)}</p>
                  <p className="text-xs text-tg-hint">
                    {formatTimestamp(tx.created_at)}
                    {tx.stars_amount ? ` · ${tx.stars_amount} ⭐` : ""}
                  </p>
                </div>
                <span
                  className={`shrink-0 text-sm font-semibold ${
                    isNegative ? "text-tg-destructive" : "text-tg-accent"
                  }`}
                >
                  {NUMBER_FORMATTER.format(delta)}
                </span>
              </li>
            );
          })}
        </ul>
      ) : null}

      <div className="mt-3 flex items-center justify-between text-xs text-tg-hint">
        <span data-testid="transactions-meta">
          {isLoading ? "Обновляем…" : data ? `Стр. ${page} из ${Math.max(1, Math.ceil(data.total / data.limit))}` : ""}
        </span>
        <div className="flex gap-2">
          <Button
            variant="secondary"
            onClick={() => onPageChange(Math.max(1, page - 1))}
            disabled={page <= 1 || isLoading}
            data-testid="tx-prev"
          >
            Назад
          </Button>
          <Button
            variant="secondary"
            onClick={() => onPageChange(page + 1)}
            disabled={!data?.has_more || isLoading}
            data-testid="tx-next"
          >
            Дальше
          </Button>
        </div>
      </div>
    </Card>
  );
}
