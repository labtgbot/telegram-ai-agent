import { Card } from "@/components/Card";
import { useUserStore } from "@/store/useUserStore";

export function BalancePage(): JSX.Element {
  const balance = useUserStore((s) => s.balance);

  return (
    <Card title="Token balance">
      <p className="text-3xl font-semibold" data-testid="balance">
        {balance ?? "—"}
      </p>
      <p className="mt-1 text-sm text-tg-hint">Buy more tokens with Telegram Stars.</p>
    </Card>
  );
}
