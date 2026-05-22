import { useEffect, useState } from "react";

import { BalanceCard } from "@/components/billing/BalanceCard";
import { BonusList } from "@/components/billing/BonusList";
import { PackageGrid } from "@/components/billing/PackageGrid";
import { ReferralLink } from "@/components/billing/ReferralLink";
import { TransactionList } from "@/components/billing/TransactionList";
import { useBalance } from "@/hooks/useBalance";
import { useBuyPackage } from "@/hooks/useBuyPackage";
import { usePackages } from "@/hooks/usePackages";
import { useReferral } from "@/hooks/useReferral";
import { useTransactions } from "@/hooks/useTransactions";
import { useUserStore } from "@/store/useUserStore";
import type { TransactionType } from "@/types/billing";

export function BalancePage(): JSX.Element {
  const balance = useBalance();
  const packages = usePackages();
  const referral = useReferral();
  const buyPackage = useBuyPackage();

  const setBalance = useUserStore((s) => s.setBalance);

  const [page, setPage] = useState(1);
  const [filter, setFilter] = useState<TransactionType | null>(null);
  const [purchaseNotice, setPurchaseNotice] = useState<string | null>(null);

  const transactions = useTransactions({ page, limit: 10, type: filter });

  useEffect(() => {
    if (typeof balance.data?.token_balance === "number") {
      setBalance(balance.data.token_balance);
    }
  }, [balance.data?.token_balance, setBalance]);

  const onBuy = (code: string): void => {
    setPurchaseNotice(null);
    buyPackage.mutate(code, {
      onSuccess: (result) => {
        if (result.payment.status === "completed") {
          setPurchaseNotice(
            `Готово! Начислено ${result.payment.tokens_credited} токенов.`,
          );
        } else if (result.telegramStatus === "cancelled") {
          setPurchaseNotice("Покупка отменена.");
        } else if (result.payment.status === "failed") {
          setPurchaseNotice("Платёж не прошёл, попробуйте ещё раз.");
        } else {
          setPurchaseNotice(
            "Платёж в обработке. Баланс обновится автоматически после подтверждения.",
          );
        }
      },
      onError: (err) => {
        setPurchaseNotice(`Не удалось создать счёт: ${err.message}`);
      },
    });
  };

  const onFilterChange = (next: TransactionType | null): void => {
    setFilter(next);
    setPage(1);
  };

  const buyingCode = buyPackage.isPending ? buyPackage.variables ?? null : null;

  return (
    <div className="flex flex-col gap-4">
      <BalanceCard
        balance={balance.data}
        isLoading={balance.isFetching}
        error={(balance.error as Error | null) ?? null}
      />

      {purchaseNotice ? (
        <div
          className="rounded-tg border border-tg-separator bg-tg-section-bg px-4 py-2 text-sm text-tg-text"
          data-testid="purchase-notice"
          role="status"
        >
          {purchaseNotice}
        </div>
      ) : null}

      <PackageGrid
        packages={packages.data?.items}
        isLoading={packages.isLoading}
        error={(packages.error as Error | null) ?? null}
        buyingCode={buyingCode}
        onBuy={onBuy}
      />

      <BonusList
        dailyAvailable={balance.data?.daily_bonus_available}
        hasReferral={Boolean(referral.data?.referral_code)}
      />

      <ReferralLink
        data={referral.data}
        isLoading={referral.isLoading}
        error={(referral.error as Error | null) ?? null}
      />

      <TransactionList
        data={transactions.data}
        isLoading={transactions.isFetching}
        error={(transactions.error as Error | null) ?? null}
        page={page}
        filter={filter}
        onPageChange={setPage}
        onFilterChange={onFilterChange}
      />
    </div>
  );
}
