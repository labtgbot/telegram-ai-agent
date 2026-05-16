import { Card, CardSubtitle, CardTitle } from "@/components/ui/card";

export const metadata = { title: "Analytics — Admin CRM" };

export default function AnalyticsPage() {
  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-semibold text-slate-900 dark:text-slate-100">Analytics</h1>
        <p className="text-sm text-slate-500 dark:text-slate-400">
          Funnel, retention, LTV, token spend per service. Read-only for analysts.
        </p>
      </header>
      <Card>
        <CardTitle>Coming next</CardTitle>
        <CardSubtitle>Charts driven by <code>GET /admin/analytics/*</code>.</CardSubtitle>
      </Card>
    </div>
  );
}
