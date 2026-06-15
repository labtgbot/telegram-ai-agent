import type { ReactElement } from "react";
import { useEffect, useMemo, useState } from "react";

import { Button } from "@/components/Button";
import { Card } from "@/components/Card";
import { Select } from "@/components/Select";
import { useTranslation } from "@/i18n/useTranslation";
import type { TranslationKey } from "@/i18n";
import { userApi } from "@/services/userApi";
import { SERVICE_TYPES, normalizeServiceType } from "@/types/profile";
import type { ServiceType, UsageHistoryItem, UsageHistoryPage } from "@/types/profile";

const PAGE_SIZE = 10;
type FilterValue = ServiceType | "all";

const SERVICE_LABEL_KEYS: Record<ServiceType, TranslationKey> = {
  text: "history.serviceText",
  image: "history.serviceImage",
  video: "history.serviceVideo",
  voice: "history.serviceVoice",
  search: "history.serviceSearch",
  document: "history.serviceDocument",
  other: "history.serviceOther",
};

function formatDateTime(value: string, language: string): string {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return new Intl.DateTimeFormat(language === "ru" ? "ru-RU" : "en-US", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(parsed);
}

function statusKey(status: string | null): TranslationKey | null {
  if (!status) return null;
  const lower = status.toLowerCase();
  if (lower === "success" || lower === "ok" || lower === "completed") {
    return "history.statusSuccess";
  }
  if (lower === "error" || lower === "failed" || lower === "failure") {
    return "history.statusError";
  }
  if (lower === "pending" || lower === "queued" || lower === "processing") {
    return "history.statusPending";
  }
  return null;
}

export function HistoryPage(): ReactElement {
  const { t, language } = useTranslation();
  const [filter, setFilter] = useState<FilterValue>("all");
  const [page, setPage] = useState(1);
  const [data, setData] = useState<UsageHistoryPage | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  const filterOptions = useMemo<ReadonlyArray<{ value: FilterValue; label: string }>>(
    () => [
      { value: "all", label: t("history.all") },
      ...SERVICE_TYPES.map((service) => ({
        value: service as FilterValue,
        label: t(SERVICE_LABEL_KEYS[service]),
      })),
    ],
    [t],
  );

  useEffect(() => {
    let ignore = false;

    const load = async (): Promise<void> => {
      setLoading(true);
      setError(null);
      try {
        const result = await userApi.getUsageHistory({
          page,
          limit: PAGE_SIZE,
          ...(filter !== "all" ? { service_type: filter } : {}),
        });
        if (ignore) return;
        setData(result);
      } catch {
        if (ignore) return;
        setError(t("history.error"));
        setData(null);
      } finally {
        if (!ignore) {
          setLoading(false);
        }
      }
    };

    void load();

    return () => {
      ignore = true;
    };
  }, [page, filter, reloadKey, t]);

  const handleFilterChange = (value: FilterValue): void => {
    setFilter(value);
    setPage(1);
  };

  const items = data?.items ?? [];
  const hasMore = data?.has_more ?? false;

  return (
    <div className="space-y-4">
      <Card title={t("history.title")}>
        <Select
          label={t("history.filter")}
          value={filter}
          onChange={handleFilterChange}
          options={filterOptions}
          id="history-filter"
        />
      </Card>

      {loading ? (
        <Card>
          <p className="text-sm text-tg-hint" data-testid="history-loading">
            {t("history.loading")}
          </p>
        </Card>
      ) : error ? (
        <Card>
          <p className="text-sm text-tg-destructive" role="alert">
            {error}
          </p>
          <div className="mt-3">
            <Button variant="secondary" onClick={() => setReloadKey((current) => current + 1)}>
              {t("history.retry")}
            </Button>
          </div>
        </Card>
      ) : items.length === 0 ? (
        <Card>
          <p className="text-sm text-tg-hint" data-testid="history-empty">
            {t("history.empty")}
          </p>
        </Card>
      ) : (
        <ul className="space-y-2" data-testid="history-list">
          {items.map((item) => (
            <li key={item.id}>
              <HistoryRow item={item} language={language} />
            </li>
          ))}
        </ul>
      )}

      <div className="flex items-center justify-between" data-testid="history-pager">
        <Button
          variant="secondary"
          disabled={loading || page <= 1}
          onClick={() => setPage((current) => Math.max(1, current - 1))}
        >
          {t("history.previous")}
        </Button>
        <span className="text-xs text-tg-hint">{t("history.page", { page })}</span>
        <Button
          variant="secondary"
          disabled={loading || !hasMore}
          onClick={() => setPage((current) => current + 1)}
        >
          {t("history.next")}
        </Button>
      </div>
    </div>
  );
}

interface HistoryRowProps {
  item: UsageHistoryItem;
  language: string;
}

function HistoryRow({ item, language }: HistoryRowProps): ReactElement {
  const { t } = useTranslation();
  const service = normalizeServiceType(item.service_type);
  const statusTk = statusKey(item.response_status);

  return (
    <div className="rounded-tg bg-tg-section-bg p-3 shadow-tg">
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium">{t(SERVICE_LABEL_KEYS[service])}</span>
        <span className="text-sm font-semibold">
          {t("history.tokens", { count: item.tokens_consumed })}
        </span>
      </div>
      <div className="mt-1 flex items-center justify-between text-xs text-tg-hint">
        <time dateTime={item.created_at}>{formatDateTime(item.created_at, language)}</time>
        {statusTk ? <span>{t(statusTk)}</span> : null}
      </div>
      {item.processing_time_ms != null ? (
        <div className="mt-1 text-xs text-tg-hint">
          {t("history.durationMs", { ms: item.processing_time_ms })}
        </div>
      ) : null}
    </div>
  );
}
