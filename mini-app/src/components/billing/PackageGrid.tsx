import type { ReactElement } from "react";
import { Card } from "@/components/Card";
import { PackageCard } from "@/components/billing/PackageCard";
import type { PackageItem } from "@/types/billing";

interface PackageGridProps {
  packages: PackageItem[] | undefined;
  isLoading: boolean;
  error: Error | null;
  buyingCode: string | null;
  onBuy: (code: string) => void;
}

const HIGHLIGHT_CODE = "premium";

export function PackageGrid({
  packages,
  isLoading,
  error,
  buyingCode,
  onBuy,
}: PackageGridProps): ReactElement {
  if (error) {
    return (
      <Card title="Пакеты">
        <p className="text-sm text-tg-destructive" data-testid="packages-error">
          Не удалось загрузить пакеты: {error.message}
        </p>
      </Card>
    );
  }

  if (isLoading && !packages) {
    return (
      <Card title="Пакеты">
        <p className="text-sm text-tg-hint" data-testid="packages-loading">
          Загружаем пакеты…
        </p>
      </Card>
    );
  }

  if (!packages || packages.length === 0) {
    return (
      <Card title="Пакеты">
        <p className="text-sm text-tg-hint">Пакеты временно недоступны.</p>
      </Card>
    );
  }

  return (
    <Card title="Пакеты">
      <div className="grid gap-3 sm:grid-cols-2" data-testid="package-grid">
        {packages.map((pkg) => (
          <PackageCard
            key={pkg.code}
            pkg={pkg}
            isHighlighted={pkg.code === HIGHLIGHT_CODE}
            isBuying={buyingCode === pkg.code}
            disabled={buyingCode !== null && buyingCode !== pkg.code}
            onBuy={onBuy}
          />
        ))}
      </div>
    </Card>
  );
}
