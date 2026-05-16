import { Card, CardSubtitle, CardTitle } from "@/components/ui/card";

export const metadata = { title: "Pricing — Admin CRM" };

export default function PricingPage() {
  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-semibold text-slate-900 dark:text-slate-100">Pricing</h1>
        <p className="text-sm text-slate-500 dark:text-slate-400">
          Edit packages, seasonal discounts, global modifiers. Super-admin only.
        </p>
      </header>
      <Card>
        <CardTitle>Coming next</CardTitle>
        <CardSubtitle>Package editor with diff preview and audit-log entry.</CardSubtitle>
      </Card>
    </div>
  );
}
