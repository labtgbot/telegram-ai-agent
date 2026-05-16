import { Card, CardSubtitle, CardTitle } from "@/components/ui/card";
import { AdminUsersList } from "@/components/admin-system/admin-users-list";
import { ComposioEditor } from "@/components/admin-system/composio-editor";
import { MaintenanceToggle } from "@/components/admin-system/maintenance-toggle";
import { RateLimitsEditor } from "@/components/admin-system/rate-limits-editor";
import {
  fetchAdminUsers,
  fetchComposioState,
  fetchMaintenanceState,
  fetchRateLimits,
} from "@/lib/admin-system/server";
import { ApiError, isApiError } from "@/lib/api/errors";
import { roleSatisfies } from "@/lib/auth/roles";
import { getAdminSession } from "@/lib/auth/session";

export const metadata = { title: "System — Admin CRM" };
export const dynamic = "force-dynamic";

export default async function SystemPage() {
  const session = await getAdminSession();
  const canToggleMaintenance = roleSatisfies(session?.role, "support_admin");
  const canEditRateLimits = roleSatisfies(session?.role, "super_admin");
  const canEditComposio = roleSatisfies(session?.role, "support_admin");
  const canManageAdmins = roleSatisfies(session?.role, "super_admin");

  const [maintenance, rateLimits, composio, admins] = await Promise.all([
    safeFetch(() => fetchMaintenanceState()),
    safeFetch(() => fetchRateLimits()),
    safeFetch(() => fetchComposioState()),
    safeFetch(() => fetchAdminUsers({ limit: 50 })),
  ]);

  const errors = [maintenance, rateLimits, composio, admins]
    .filter((r) => r.error)
    .map((r) => r.error as string);

  const currentUserId = session ? Number.parseInt(session.sub, 10) : undefined;

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-semibold text-slate-900 dark:text-slate-100">System</h1>
        <p className="text-sm text-slate-500 dark:text-slate-400">
          Maintenance mode, rate limits, Composio integrations, and admin roles. Mutations are
          recorded in the admin audit log.
        </p>
      </header>

      {errors.length > 0 && (
        <Card>
          <CardTitle>Couldn&apos;t load some sections</CardTitle>
          <CardSubtitle>{errors.join(" · ")}</CardSubtitle>
        </Card>
      )}

      {maintenance.data && (
        <MaintenanceToggle initial={maintenance.data} canEdit={canToggleMaintenance} />
      )}
      {rateLimits.data && (
        <RateLimitsEditor initial={rateLimits.data} canEdit={canEditRateLimits} />
      )}
      {composio.data && <ComposioEditor initial={composio.data} canEdit={canEditComposio} />}
      {admins.data && (
        <AdminUsersList
          initial={admins.data}
          canEdit={canManageAdmins}
          currentUserId={currentUserId !== undefined && !Number.isNaN(currentUserId) ? currentUserId : undefined}
        />
      )}
    </div>
  );
}

async function safeFetch<T>(loader: () => Promise<T>): Promise<{ data?: T; error?: string }> {
  try {
    return { data: await loader() };
  } catch (err) {
    return { error: formatFetchError(err) };
  }
}

function formatFetchError(err: unknown): string {
  if (isApiError(err)) {
    if (err.status === 403) return "You don't have permission to view this section.";
    if (err.status === 401) return "Your session expired — please log in again.";
    return err.message || `Request failed (${err.status}).`;
  }
  if (err instanceof Error) return err.message;
  if (err instanceof ApiError) return err.message;
  return "Failed to load system settings.";
}
