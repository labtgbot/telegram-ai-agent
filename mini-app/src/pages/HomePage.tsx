import { Card } from "@/components/Card";
import { Button } from "@/components/Button";
import { useUserStore } from "@/store/useUserStore";

export function HomePage(): JSX.Element {
  const user = useUserStore((s) => s.user);
  const greeting = user?.first_name ?? user?.username ?? "there";

  return (
    <div className="space-y-4">
      <Card title="Welcome">
        <p className="text-sm">
          Hi <span className="font-medium">{greeting}</span> — this is the Telegram AI Agent Mini
          App skeleton.
        </p>
      </Card>

      <Card title="Get started">
        <p className="mb-3 text-sm text-tg-hint">
          Replace the placeholder pages with your token, generation, and subscription flows.
        </p>
        <Button>Generate</Button>
      </Card>
    </div>
  );
}
