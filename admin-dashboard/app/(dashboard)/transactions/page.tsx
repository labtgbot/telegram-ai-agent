import { Card, CardSubtitle, CardTitle } from "@/components/ui/card";

export const metadata = { title: "Transactions — Admin CRM" };

export default function TransactionsPage() {
  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-semibold text-slate-900 dark:text-slate-100">Transactions</h1>
        <p className="text-sm text-slate-500 dark:text-slate-400">
          Stars payments, manual adjustments, refunds. Hooks into Phase 2 payment service.
        </p>
      </header>
      <Card>
        <CardTitle>Coming next</CardTitle>
        <CardSubtitle>Filterable table, retry webhook, refund flow.</CardSubtitle>
      </Card>
    </div>
  );
}
