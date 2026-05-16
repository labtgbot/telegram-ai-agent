import { Card, CardSubtitle, CardTitle } from "@/components/ui/card";
import { ContentHistory } from "@/components/admin-content/content-history";
import { FaqsEditor } from "@/components/admin-content/faqs-editor";
import { PromptTemplatesEditor } from "@/components/admin-content/prompt-templates-editor";
import { WelcomesEditor } from "@/components/admin-content/welcomes-editor";
import {
  fetchContentHistory,
  fetchFaqItems,
  fetchPromptTemplates,
  fetchWelcomeMessages,
} from "@/lib/admin-content/server";
import { ApiError, isApiError } from "@/lib/api/errors";
import { roleSatisfies } from "@/lib/auth/roles";
import { getAdminSession } from "@/lib/auth/session";

export const metadata = { title: "Content — Admin CRM" };
export const dynamic = "force-dynamic";

export default async function ContentPage() {
  const session = await getAdminSession();
  const canEdit = roleSatisfies(session?.role, "support_admin");

  const [prompts, faqs, welcomes, history] = await Promise.all([
    safeFetch(() => fetchPromptTemplates({ limit: 50 })),
    safeFetch(() => fetchFaqItems({ limit: 50 })),
    safeFetch(() => fetchWelcomeMessages({ limit: 50 })),
    safeFetch(() => fetchContentHistory({ limit: 50 })),
  ]);

  const errors = [prompts, faqs, welcomes, history]
    .filter((r) => r.error)
    .map((r) => r.error as string);

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-semibold text-slate-900 dark:text-slate-100">Content</h1>
        <p className="text-sm text-slate-500 dark:text-slate-400">
          Prompt templates, FAQ, and welcome messages.{" "}
          {canEdit
            ? "Every mutation is recorded in the admin audit log."
            : "Read-only — support-admin role required to edit."}
        </p>
      </header>

      {errors.length > 0 && (
        <Card>
          <CardTitle>Couldn&apos;t load some sections</CardTitle>
          <CardSubtitle>{errors.join(" · ")}</CardSubtitle>
        </Card>
      )}

      {prompts.data && <PromptTemplatesEditor initial={prompts.data} canEdit={canEdit} />}
      {faqs.data && <FaqsEditor initial={faqs.data} canEdit={canEdit} />}
      {welcomes.data && <WelcomesEditor initial={welcomes.data} canEdit={canEdit} />}
      {history.data && <ContentHistory initial={history.data} />}
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
    if (err.status === 403) return "You don't have permission to view this content.";
    if (err.status === 401) return "Your session expired — please log in again.";
    return err.message || `Request failed (${err.status}).`;
  }
  if (err instanceof Error) return err.message;
  if (err instanceof ApiError) return err.message;
  return "Failed to load content.";
}
