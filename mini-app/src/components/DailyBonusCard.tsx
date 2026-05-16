import { useCallback, useEffect, useState } from "react";

import { Button } from "@/components/Button";
import { Card } from "@/components/Card";
import { useTranslation } from "@/i18n/useTranslation";
import { ApiError, userApi } from "@/services/userApi";
import { useUserStore } from "@/store/useUserStore";
import type { DailyBonusStatus } from "@/types/profile";

function formatTimeUtc(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const hh = String(d.getUTCHours()).padStart(2, "0");
  const mm = String(d.getUTCMinutes()).padStart(2, "0");
  return `${hh}:${mm}`;
}

export function DailyBonusCard(): JSX.Element {
  const { t } = useTranslation();
  const setBalance = useUserStore((s) => s.setBalance);
  const [status, setStatus] = useState<DailyBonusStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [claiming, setClaiming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [claimedAmount, setClaimedAmount] = useState<number | null>(null);
  const [claimedStreak, setClaimedStreak] = useState<number | null>(null);

  const load = useCallback(async (): Promise<void> => {
    setLoading(true);
    setError(null);
    try {
      const snapshot = await userApi.getDailyBonusStatus();
      setStatus(snapshot);
    } catch {
      setError(t("dailyBonus.error"));
      setStatus(null);
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    void load();
  }, [load]);

  const claim = useCallback(async (): Promise<void> => {
    if (!status || !status.available || claiming) return;
    setClaiming(true);
    setError(null);
    try {
      const result = await userApi.claimDailyBonus();
      setClaimedAmount(result.amount);
      setClaimedStreak(result.streak_day);
      setBalance(result.new_balance);
      const previewIndex = Math.min(result.streak_day, status.amounts.length - 1);
      const previewAmount =
        previewIndex >= 0 && status.amounts[previewIndex] !== undefined
          ? (status.amounts[previewIndex] as number)
          : result.amount;
      setStatus({
        available: false,
        enabled: status.enabled,
        streak_day: result.streak_day,
        next_amount: previewAmount,
        last_claim_date: result.claim_date,
        next_available_at: result.next_available_at,
        amounts: status.amounts,
      });
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        // someone else already claimed (e.g. via the bot) — re-read state
        await load();
      } else if (err instanceof ApiError && err.status === 403) {
        setError(t("dailyBonus.disabled"));
      } else {
        setError(t("dailyBonus.error"));
      }
    } finally {
      setClaiming(false);
    }
  }, [status, claiming, setBalance, load, t]);

  if (loading && !status) {
    return (
      <Card title={t("dailyBonus.title")}>
        <p className="text-sm text-tg-hint" data-testid="daily-bonus-loading">
          {t("dailyBonus.loading")}
        </p>
      </Card>
    );
  }

  if (error && !status) {
    return (
      <Card title={t("dailyBonus.title")}>
        <p className="text-sm text-tg-destructive" role="alert">
          {error}
        </p>
        <div className="mt-3">
          <Button variant="secondary" onClick={() => void load()}>
            {t("dailyBonus.retry")}
          </Button>
        </div>
      </Card>
    );
  }

  if (!status) return <></>;

  if (!status.enabled) {
    return (
      <Card title={t("dailyBonus.title")}>
        <p className="text-sm text-tg-hint" data-testid="daily-bonus-disabled">
          {t("dailyBonus.disabled")}
        </p>
      </Card>
    );
  }

  const nextAtLabel = formatTimeUtc(status.next_available_at);
  const ladderLabel = status.amounts.length > 0 ? status.amounts.join(" → ") : "—";
  const streakDayDisplay = status.available
    ? Math.max(status.streak_day + 1, 1)
    : status.streak_day;

  return (
    <Card title={t("dailyBonus.title")}>
      <p className="text-sm text-tg-hint">{t("dailyBonus.subtitle")}</p>
      <dl className="mt-3 text-sm">
        <div className="flex items-center justify-between py-1" data-testid="daily-bonus-streak">
          <dt className="text-tg-hint">{t("dailyBonus.streak", { day: streakDayDisplay })}</dt>
          <dd className="text-right font-semibold">
            {t("dailyBonus.rewardTokens", { amount: status.next_amount })}
          </dd>
        </div>
        <div className="flex items-center justify-between py-1" data-testid="daily-bonus-ladder">
          <dt className="text-tg-hint">{t("dailyBonus.ladder")}</dt>
          <dd className="text-right font-mono text-xs">{ladderLabel}</dd>
        </div>
      </dl>

      {claimedAmount !== null && claimedStreak !== null ? (
        <p
          className="mt-3 text-sm font-medium text-tg-link"
          data-testid="daily-bonus-claimed"
          role="status"
        >
          {t("dailyBonus.claimedTitle")}{" "}
          {t("dailyBonus.claimedBody", { amount: claimedAmount, day: claimedStreak })}
        </p>
      ) : null}

      {error ? (
        <p className="mt-3 text-sm text-tg-destructive" role="alert">
          {error}
        </p>
      ) : null}

      <div className="mt-3">
        {status.available ? (
          <Button
            data-testid="daily-bonus-claim"
            onClick={() => void claim()}
            disabled={claiming}
          >
            {claiming
              ? t("dailyBonus.claiming")
              : t("dailyBonus.claim", { amount: status.next_amount })}
          </Button>
        ) : (
          <p className="text-sm text-tg-hint" data-testid="daily-bonus-cooldown">
            {t("dailyBonus.cooldown", { time: nextAtLabel })}
          </p>
        )}
      </div>
    </Card>
  );
}
