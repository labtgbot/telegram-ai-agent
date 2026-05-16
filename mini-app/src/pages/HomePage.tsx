import { Button } from "@/components/Button";
import { Card } from "@/components/Card";
import { DailyBonusCard } from "@/components/DailyBonusCard";
import { useTranslation } from "@/i18n/useTranslation";
import { useUserStore } from "@/store/useUserStore";

export function HomePage(): JSX.Element {
  const user = useUserStore((s) => s.user);
  const { t } = useTranslation();
  const greeting = user?.first_name ?? user?.username ?? "there";

  return (
    <div className="space-y-4">
      <Card title={t("home.welcome")}>
        <p className="text-sm">{t("home.greeting", { name: greeting })}</p>
      </Card>

      <DailyBonusCard />

      <Card title={t("home.getStarted")}>
        <p className="mb-3 text-sm text-tg-hint">{t("home.getStartedBody")}</p>
        <Button>{t("home.generate")}</Button>
      </Card>
    </div>
  );
}
