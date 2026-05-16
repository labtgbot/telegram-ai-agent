import { Card, CardSubtitle, CardTitle } from "@/components/ui/card";
import { UserDetailDrawer } from "@/components/admin-users/user-detail-drawer";
import { UsersFilters } from "@/components/admin-users/users-filters";
import { UsersPagination, UsersTable } from "@/components/admin-users/users-table";
import { exportUsersCsvUrl, fetchUsers } from "@/lib/admin-users/server";
import { parseUserListQuery } from "@/lib/admin-users/url";
import { ApiError, isApiError } from "@/lib/api/errors";
import { formatInteger } from "@/lib/dashboard/format";

export const metadata = { title: "Users — Admin CRM" };
// Re-render on every request — filters live in the URL and tokens may rotate.
export const dynamic = "force-dynamic";

interface UsersPageProps {
  searchParams: Record<string, string | string[] | undefined>;
}

export default async function UsersPage({ searchParams }: UsersPageProps) {
  const filters = parseUserListQuery(searchParams);
  const selectedUserId = parsePositiveInt(searchParams.user);

  let result;
  let fetchError: string | undefined;
  try {
    result = await fetchUsers(filters);
  } catch (err) {
    fetchError = formatFetchError(err);
  }

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-semibold text-slate-900 dark:text-slate-100">Users</h1>
        <p className="text-sm text-slate-500 dark:text-slate-400">
          Search, sort and filter the user base. Click a row to open a detail drawer with
          transactions, services usage, referrals, and admin actions.
        </p>
      </header>

      <Card className="space-y-4">
        <UsersFilters
          initialSearch={filters.search ?? ""}
          initialPremium={filters.is_premium}
          initialBanned={filters.is_banned}
          csvHref={exportUsersCsvUrl(filters)}
        />

        {fetchError && (
          <p className="rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700 dark:border-rose-700/40 dark:bg-rose-900/30 dark:text-rose-200">
            {fetchError}
          </p>
        )}

        {result && (
          <>
            <UsersTable
              rows={result.items}
              sort={filters.sort ?? "created_at"}
              direction={filters.direction ?? "desc"}
              selectedId={selectedUserId}
            />
            <UsersPagination
              page={result.page}
              limit={result.limit}
              total={result.total}
              hasMore={result.has_more}
            />
          </>
        )}
      </Card>

      <Card>
        <CardTitle>How this page works</CardTitle>
        <CardSubtitle>
          Every action — token grants, bans, broadcasts — is recorded in{" "}
          <code>/admin/audit-log</code>. The CSV export honours the active filters and is
          downloaded directly from the backend.{" "}
          {result && (
            <>
              Currently showing <strong>{formatInteger(result.items.length)}</strong> of{" "}
              <strong>{formatInteger(result.total)}</strong> users on page {result.page}.
            </>
          )}
        </CardSubtitle>
      </Card>

      <UserDetailDrawer userId={selectedUserId} />
    </div>
  );
}

function parsePositiveInt(value: string | string[] | undefined): number | undefined {
  if (Array.isArray(value)) value = value[0];
  if (!value) return undefined;
  const parsed = Number.parseInt(value, 10);
  if (!Number.isFinite(parsed) || parsed <= 0) return undefined;
  return parsed;
}

function formatFetchError(err: unknown): string {
  if (isApiError(err)) {
    if (err.status === 403) return "You don't have permission to view this list.";
    if (err.status === 401) return "Your session expired — please log in again.";
    return err.message || `Request failed (${err.status}).`;
  }
  if (err instanceof Error) return err.message;
  if (err instanceof ApiError) return err.message;
  return "Failed to load users.";
}
