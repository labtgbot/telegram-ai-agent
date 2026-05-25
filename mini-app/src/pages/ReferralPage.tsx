import type { ReactElement } from "react";
import { useCallback, useEffect, useState } from "react";

import { Button } from "@/components/Button";
import { Card } from "@/components/Card";
import { useTranslation } from "@/i18n/useTranslation";
import { userApi } from "@/services/userApi";
import { WebApp } from "@/services/telegram";
import type { ReferralSummary } from "@/types/profile";

const REFERRAL_BONUS_TOKENS = 100;

type CopyTarget = "link" | "code";

function shareViaTelegram(link: string, message: string): boolean {
  const sdk = WebApp as unknown as {
    openTelegramLink?: (url: string) => void;
  };
  if (typeof sdk.openTelegramLink !== "function") return false;
  const shareUrl = `https://t.me/share/url?url=${encodeURIComponent(link)}&text=${encodeURIComponent(message)}`;
  try {
    sdk.openTelegramLink(shareUrl);
    return true;
  } catch {
    return false;
  }
}

export function ReferralPage(): ReactElement {
  const { t } = useTranslation();
  const [data, setData] = useState<ReferralSummary | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState<CopyTarget | null>(null);
  const [copyError, setCopyError] = useState<string | null>(null);

  const load = useCallback(async (): Promise<void> => {
    setLoading(true);
    setError(null);
    try {
      const summary = await userApi.getReferralSummary();
      setData(summary);
    } catch {
      setError(t("referral.error"));
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    void load();
  }, [load]);

  const copy = useCallback(
    async (target: CopyTarget, value: string): Promise<void> => {
      setCopied(null);
      setCopyError(null);
      try {
        if (typeof navigator !== "undefined" && navigator.clipboard?.writeText) {
          await navigator.clipboard.writeText(value);
          setCopied(target);
        } else {
          setCopyError(t("referral.copyFailed"));
        }
      } catch {
        setCopyError(t("referral.copyFailed"));
      }
    },
    [t],
  );

  const handleShare = useCallback((): void => {
    if (!data) return;
    const message = t("referral.subtitle", { bonus: REFERRAL_BONUS_TOKENS });
    const shared = shareViaTelegram(data.referral_link, message);
    if (!shared) {
      void copy("link", data.referral_link);
    }
  }, [data, t, copy]);

  if (loading && !data) {
    return (
      <Card title={t("referral.title")}>
        <p className="text-sm text-tg-hint" data-testid="referral-loading">
          {t("referral.loading")}
        </p>
      </Card>
    );
  }

  if (error) {
    return (
      <Card title={t("referral.title")}>
        <p className="text-sm text-tg-destructive" role="alert">
          {error}
        </p>
        <div className="mt-3">
          <Button variant="secondary" onClick={() => void load()}>
            {t("referral.retry")}
          </Button>
        </div>
      </Card>
    );
  }

  if (!data) {
    return (
      <Card title={t("referral.title")}>
        <p className="text-sm text-tg-hint">{t("referral.emptyState")}</p>
      </Card>
    );
  }

  return (
    <div className="space-y-4">
      <Card title={t("referral.title")}>
        <p className="text-sm text-tg-hint">
          {t("referral.subtitle", { bonus: REFERRAL_BONUS_TOKENS })}
        </p>
      </Card>

      <Card>
        <div className="space-y-3">
          <div>
            <label
              htmlFor="referral-link"
              className="block text-xs font-medium uppercase tracking-wide text-tg-section-header"
            >
              {t("referral.yourLink")}
            </label>
            <input
              id="referral-link"
              data-testid="referral-link"
              readOnly
              value={data.referral_link}
              onFocus={(event) => event.currentTarget.select()}
              className="mt-1 w-full rounded-tg bg-tg-bg px-3 py-2 text-sm text-tg-text shadow-tg focus:outline-none focus:ring-2 focus:ring-tg-accent"
            />
          </div>
          <div className="flex flex-wrap gap-2">
            <Button onClick={() => void copy("link", data.referral_link)}>
              {t("referral.copyLink")}
            </Button>
            <Button variant="secondary" onClick={() => void copy("code", data.referral_code)}>
              {t("referral.copyCode")}
            </Button>
            <Button variant="ghost" onClick={handleShare}>
              {t("referral.shareCta")}
            </Button>
          </div>
          <div className="flex items-center justify-between text-xs">
            <span className="text-tg-hint">
              {t("referral.yourCode")}:{" "}
              <span className="font-mono font-semibold text-tg-text" data-testid="referral-code">
                {data.referral_code}
              </span>
            </span>
            {copied ? (
              <span className="text-tg-link" data-testid="referral-copied" role="status">
                {t("referral.copied")}
              </span>
            ) : copyError ? (
              <span className="text-tg-destructive" role="alert">
                {copyError}
              </span>
            ) : null}
          </div>
        </div>
      </Card>

      <Card title={t("referral.statsTitle")}>
        {data.referrals_count === 0 && data.bonus_tokens_earned === 0 ? (
          <p className="text-sm text-tg-hint" data-testid="referral-empty">
            {t("referral.emptyState")}
          </p>
        ) : (
          <dl className="text-sm">
            <div
              className="flex items-center justify-between py-2"
              data-testid="referral-count-row"
            >
              <dt className="text-tg-hint">{t("referral.referralsCount")}</dt>
              <dd className="text-right font-semibold">{data.referrals_count}</dd>
            </div>
            <div
              className="flex items-center justify-between py-2"
              data-testid="referral-bonus-row"
            >
              <dt className="text-tg-hint">{t("referral.bonusEarned")}</dt>
              <dd className="text-right font-semibold">{data.bonus_tokens_earned}</dd>
            </div>
          </dl>
        )}
      </Card>
    </div>
  );
}
