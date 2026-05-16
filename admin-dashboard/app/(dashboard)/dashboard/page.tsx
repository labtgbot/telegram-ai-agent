import { DashboardScreen } from "@/components/dashboard/dashboard-screen";
import { buildDashboardSnapshot } from "@/lib/dashboard/mock";

export const metadata = { title: "Dashboard — Admin CRM" };
// Server-rendered freshly on every request — the snapshot is generated each
// time so the SSR HTML matches the polled fetch and the page never goes stale
// on a static export.
export const dynamic = "force-dynamic";

export default function DashboardPage() {
  const initialSnapshot = buildDashboardSnapshot("7d");
  return <DashboardScreen initialSnapshot={initialSnapshot} />;
}
