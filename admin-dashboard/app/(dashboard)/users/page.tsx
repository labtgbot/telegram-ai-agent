import { Card, CardSubtitle, CardTitle } from "@/components/ui/card";

export const metadata = { title: "Users — Admin CRM" };

export default function UsersPage() {
  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-semibold text-slate-900 dark:text-slate-100">Users</h1>
        <p className="text-sm text-slate-500 dark:text-slate-400">
          Search, ban / unban, grant premium, adjust tokens. Backed by <code>GET /admin/users</code>.
        </p>
      </header>
      <Card>
        <CardTitle>Coming next</CardTitle>
        <CardSubtitle>
          Table with filters, user detail drawer, manual token grant. Tracked in a follow-up issue.
        </CardSubtitle>
      </Card>
    </div>
  );
}
