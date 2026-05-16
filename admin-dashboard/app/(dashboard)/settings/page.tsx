import { Card, CardSubtitle, CardTitle } from "@/components/ui/card";

export const metadata = { title: "Settings — Admin CRM" };

export default function SettingsPage() {
  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-semibold text-slate-900 dark:text-slate-100">Settings</h1>
        <p className="text-sm text-slate-500 dark:text-slate-400">
          Maintenance mode, daily bonus, rate limits, Composio toggles. Super-admin only.
        </p>
      </header>
      <Card>
        <CardTitle>Coming next</CardTitle>
        <CardSubtitle>
          Form bound to <code>admin_settings</code> with optimistic write-through.
        </CardSubtitle>
      </Card>
    </div>
  );
}
