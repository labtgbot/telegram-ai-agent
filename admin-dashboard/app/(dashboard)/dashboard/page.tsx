import { Card, CardSubtitle, CardTitle } from "@/components/ui/card";

export const metadata = { title: "Dashboard — Admin CRM" };

const KPI = [
  { label: "Users total", placeholder: "—" },
  { label: "Active 7d", placeholder: "—" },
  { label: "Revenue (MRR)", placeholder: "—" },
  { label: "Tokens sold 30d", placeholder: "—" },
];

export default function DashboardPage() {
  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-semibold text-slate-900 dark:text-slate-100">Dashboard</h1>
        <p className="text-sm text-slate-500 dark:text-slate-400">
          KPIs, charts and recent activity. Backed by <code>GET /admin/dashboard</code> (Phase 3).
        </p>
      </header>
      <section className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {KPI.map((kpi) => (
          <Card key={kpi.label}>
            <CardSubtitle>{kpi.label}</CardSubtitle>
            <p className="mt-2 text-3xl font-semibold text-slate-900 dark:text-slate-100">
              {kpi.placeholder}
            </p>
          </Card>
        ))}
      </section>
      <Card>
        <CardTitle>Welcome</CardTitle>
        <CardSubtitle>
          This panel is the Phase 3 scaffold (issue #23). Subsequent issues wire each section to the
          backend.
        </CardSubtitle>
      </Card>
    </div>
  );
}
