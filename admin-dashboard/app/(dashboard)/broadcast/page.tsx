import { Card, CardSubtitle, CardTitle } from "@/components/ui/card";
import { BroadcastComposer } from "@/components/admin-broadcasts/broadcast-composer";
import { BroadcastsList } from "@/components/admin-broadcasts/broadcasts-list";
import { fetchBroadcasts } from "@/lib/admin-broadcasts/server";
import { ApiError, isApiError } from "@/lib/api/errors";
import { roleSatisfies } from "@/lib/auth/roles";
import { getAdminSession } from "@/lib/auth/session";

export const metadata = { title: "Broadcast — Admin CRM" };
export const dynamic = "force-dynamic";

export default async function BroadcastPage() {
  const session = await getAdminSession();
  const canCreate = roleSatisfies(session?.role, "support_admin");
  const canCancel = canCreate;

  let initialList;
  let fetchError: string | undefined;
  try {
    initialList = await fetchBroadcasts({ page: 1, limit: 25 });
  } catch (err) {
    fetchError = formatFetchError(err);
  }

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-semibold text-slate-900 dark:text-slate-100">Broadcast</h1>
        <p className="text-sm text-slate-500 dark:text-slate-400">
          Compose targeted broadcasts, respect Telegram rate limits, schedule sends.
          {canCreate
            ? " Every send is recorded in the admin audit log."
            : " Read-only — support-admin role required to send."}
        </p>
      </header>

      {fetchError && (
        <Card>
          <CardTitle>Couldn&apos;t load broadcasts</CardTitle>
          <CardSubtitle>{fetchError}</CardSubtitle>
        </Card>
      )}

      <BroadcastComposer canCreate={canCreate} />

      {initialList && <BroadcastsList page={initialList} canCancel={canCancel} />}
    </div>
  );
}

function formatFetchError(err: unknown): string {
  if (isApiError(err)) {
    if (err.status === 403) return "You don't have permission to view broadcasts.";
    if (err.status === 401) return "Your session expired — please log in again.";
    return err.message || `Request failed (${err.status}).`;
  }
  if (err instanceof Error) return err.message;
  if (err instanceof ApiError) return err.message;
  return "Failed to load broadcasts.";
}
