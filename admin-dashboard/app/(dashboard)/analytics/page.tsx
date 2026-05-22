import { AnalyticsScreen } from "@/components/admin-analytics/analytics-screen";
import { Card, CardSubtitle, CardTitle } from "@/components/ui/card";
import {
  fetchLtvSummary,
  fetchRevenueSummary,
  fetchTokenUsage,
  fetchUserBehavior,
} from "@/lib/admin-analytics/server";
import { ApiError, isApiError } from "@/lib/api/errors";
import { roleSatisfies } from "@/lib/auth/roles";
import { getAdminSession } from "@/lib/auth/session";

export const metadata = { title: "Analytics — Admin CRM" };
export const dynamic = "force-dynamic";

export default async function AnalyticsPage() {
  const session = await getAdminSession();
  // CSV export is read-only but still privileged; analysts may view, but only
  // support-admins and above can pull a CSV (matches the backend audit log).
  const canExport = roleSatisfies(session?.role, "support_admin");

  let initialRevenue;
  let initialUserBehavior;
  let initialTokens;
  let initialLtv;
  let fetchError: string | undefined;
  try {
    [initialRevenue, initialUserBehavior, initialTokens, initialLtv] = await Promise.all([
      fetchRevenueSummary(),
      fetchUserBehavior(),
      fetchTokenUsage(),
      fetchLtvSummary(),
    ]);
  } catch (err) {
    fetchError = formatFetchError(err);
  }

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-semibold text-slate-900 dark:text-slate-100">Analytics</h1>
        <p className="text-sm text-slate-500 dark:text-slate-400">
          Funnel, retention, LTV, token spend per service. Read-only for analysts;
          {canExport ? " CSV export is enabled." : " CSV export requires support-admin or above."}
        </p>
      </header>

      {fetchError && (
        <Card>
          <CardTitle>Couldn&apos;t load analytics</CardTitle>
          <CardSubtitle>{fetchError}</CardSubtitle>
        </Card>
      )}

      {initialRevenue && initialUserBehavior && initialTokens && initialLtv && (
        <AnalyticsScreen
          initialRevenue={initialRevenue}
          initialUserBehavior={initialUserBehavior}
          initialTokens={initialTokens}
          initialLtv={initialLtv}
          canExport={canExport}
        />
      )}
    </div>
  );
}

function formatFetchError(err: unknown): string {
  if (isApiError(err)) {
    if (err.status === 403) return "You don't have permission to view analytics.";
    if (err.status === 401) return "Your session expired — please log in again.";
    return err.message || `Request failed (${err.status}).`;
  }
  if (err instanceof Error) return err.message;
  if (err instanceof ApiError) return err.message;
  return "Failed to load analytics.";
}
