import { Card, CardSubtitle, CardTitle } from "@/components/ui/card";

export const metadata = { title: "Broadcast — Admin CRM" };

export default function BroadcastPage() {
  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-semibold text-slate-900 dark:text-slate-100">Broadcast</h1>
        <p className="text-sm text-slate-500 dark:text-slate-400">
          Compose targeted broadcasts, respect Telegram rate limits, schedule sends.
        </p>
      </header>
      <Card>
        <CardTitle>Coming next</CardTitle>
        <CardSubtitle>Composer with segment picker and dry-run preview.</CardSubtitle>
      </Card>
    </div>
  );
}
