import type { ReactElement } from "react";
import { useCallback, useEffect, useState } from "react";

import { Avatar } from "@/components/Avatar";
import { Button } from "@/components/Button";
import { Card } from "@/components/Card";
import { useTranslation } from "@/i18n/useTranslation";
import { ApiError, userApi } from "@/services/userApi";
import { useUserStore } from "@/store/useUserStore";

function fullName(
  firstName: string | null | undefined,
  lastName: string | null | undefined,
): string | null {
  const parts = [firstName, lastName].filter((value): value is string => Boolean(value));
  return parts.length > 0 ? parts.join(" ") : null;
}

function formatDate(value: string | null | undefined, language: string): string | null {
  if (!value) return null;
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return null;
  return new Intl.DateTimeFormat(language === "ru" ? "ru-RU" : "en-US", {
    dateStyle: "long",
  }).format(parsed);
}

export function ProfilePage(): ReactElement {
  const user = useUserStore((s) => s.user);
  const setUser = useUserStore((s) => s.setUser);
  const { t, language } = useTranslation();
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async (): Promise<void> => {
    setIsRefreshing(true);
    setError(null);
    try {
      const fresh = await userApi.getProfile();
      setUser(fresh);
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) {
        setError(null);
      } else {
        setError(t("profile.refreshError"));
      }
    } finally {
      setIsRefreshing(false);
    }
  }, [setUser, t]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const displayName = fullName(user?.first_name, user?.last_name);
  const memberSince = formatDate(user?.created_at, language);
  const premiumExpires = formatDate(user?.premium_expires_at, language);

  if (!user) {
    return (
      <Card title={t("profile.title")}>
        <p className="text-sm text-tg-hint" data-testid="profile-empty">
          {t("profile.unknownUser")}
        </p>
      </Card>
    );
  }

  return (
    <div className="space-y-4">
      <Card title={t("profile.title")}>
        <div className="flex items-center gap-4">
          <Avatar
            src={user.photo_url}
            name={displayName ?? user.username ?? null}
            alt={t("profile.avatarAlt")}
          />
          <div className="min-w-0 flex-1">
            <p className="truncate text-base font-semibold" data-testid="profile-name">
              {displayName ?? user.username ?? t("profile.unknownUser")}
            </p>
            {user.username ? (
              <p className="truncate text-sm text-tg-hint" data-testid="profile-username">
                @{user.username}
              </p>
            ) : null}
          </div>
        </div>
      </Card>

      <Card>
        <dl className="text-sm">
          <ProfileRow
            label={t("profile.language")}
            value={user.language_code ?? "—"}
            testId="row-language"
          />
          <ProfileRow
            label={t("profile.premium")}
            value={
              user.is_premium
                ? premiumExpires
                  ? t("profile.premiumExpires", { date: premiumExpires })
                  : t("profile.premiumActive")
                : t("profile.premiumInactive")
            }
            testId="row-premium"
          />
          <ProfileRow
            label={t("profile.memberSince")}
            value={memberSince ?? t("common.notAvailable")}
            testId="row-member-since"
          />
          {user.referral_code ? (
            <ProfileRow
              label={t("profile.referralCode")}
              value={user.referral_code}
              testId="row-referral"
            />
          ) : null}
        </dl>
      </Card>

      <div className="flex items-center justify-between">
        {error ? (
          <p className="text-xs text-tg-destructive" role="alert">
            {error}
          </p>
        ) : (
          <span />
        )}
        <Button
          variant="secondary"
          onClick={() => void refresh()}
          disabled={isRefreshing}
          aria-label={t("profile.refresh")}
        >
          {isRefreshing ? t("profile.refreshing") : t("profile.refresh")}
        </Button>
      </div>
    </div>
  );
}

interface ProfileRowProps {
  label: string;
  value: string;
  testId?: string;
}

function ProfileRow({ label, value, testId }: ProfileRowProps): ReactElement {
  return (
    <div className="flex items-center justify-between py-2" data-testid={testId}>
      <dt className="text-tg-hint">{label}</dt>
      <dd className="text-right font-medium">{value}</dd>
    </div>
  );
}
