import { Card } from "@/components/Card";
import { useTranslation } from "@/i18n/useTranslation";
import { useUserStore } from "@/store/useUserStore";

export function BalancePage(): JSX.Element {
  const balance = useUserStore((s) => s.balance);
  const { t } = useTranslation();

  return (
    <Card title={t("balance.title")}>
      <p className="text-3xl font-semibold" data-testid="balance">
        {balance ?? t("common.notAvailable")}
      </p>
      <p className="mt-1 text-sm text-tg-hint">{t("balance.cta")}</p>
    </Card>
  );
}
