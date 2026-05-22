import { Card, CardSubtitle, CardTitle } from "@/components/ui/card";
import { PricingEditor } from "@/components/admin-pricing/pricing-editor";
import { fetchPricingConfig, fetchPricingHistory } from "@/lib/admin-pricing/server";
import { ApiError, isApiError } from "@/lib/api/errors";
import { roleSatisfies } from "@/lib/auth/roles";
import { getAdminSession } from "@/lib/auth/session";

export const metadata = { title: "Pricing — Admin CRM" };
export const dynamic = "force-dynamic";

export default async function PricingPage() {
  const session = await getAdminSession();
  const canEdit = roleSatisfies(session?.role, "super_admin");

  let initialConfig;
  let initialHistory;
  let fetchError: string | undefined;
  try {
    [initialConfig, initialHistory] = await Promise.all([
      fetchPricingConfig(),
      fetchPricingHistory(1, 25),
    ]);
  } catch (err) {
    fetchError = formatFetchError(err);
  }

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-semibold text-slate-900 dark:text-slate-100">Pricing</h1>
        <p className="text-sm text-slate-500 dark:text-slate-400">
          Edit packages, seasonal discounts, global modifiers.
          {canEdit
            ? " Saves are persisted with an audit-log entry."
            : " Read-only — super-admin role required to save changes."}
        </p>
      </header>

      {fetchError && (
        <Card>
          <CardTitle>Couldn&apos;t load pricing</CardTitle>
          <CardSubtitle>{fetchError}</CardSubtitle>
        </Card>
      )}

      {initialConfig && initialHistory && (
        <PricingEditor
          initialConfig={initialConfig}
          initialHistory={initialHistory}
          canEdit={canEdit}
        />
      )}
    </div>
  );
}

function formatFetchError(err: unknown): string {
  if (isApiError(err)) {
    if (err.status === 403) return "You don't have permission to view pricing.";
    if (err.status === 401) return "Your session expired — please log in again.";
    return err.message || `Request failed (${err.status}).`;
  }
  if (err instanceof Error) return err.message;
  if (err instanceof ApiError) return err.message;
  return "Failed to load pricing config.";
}
