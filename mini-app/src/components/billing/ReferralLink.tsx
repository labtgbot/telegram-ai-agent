import type { ReactElement } from "react";
import { useState } from "react";

import { Button } from "@/components/Button";
import { Card } from "@/components/Card";
import { WebApp } from "@/services/telegram";
import type { ReferralInfo } from "@/types/billing";

interface ReferralLinkProps {
  data: ReferralInfo | undefined;
  isLoading: boolean;
  error: Error | null;
}

async function copyToClipboard(value: string): Promise<boolean> {
  if (typeof navigator !== "undefined" && navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(value);
      return true;
    } catch {
      /* fall through */
    }
  }
  return false;
}

function shareViaTelegram(link: string): boolean {
  try {
    WebApp.openTelegramLink(`https://t.me/share/url?url=${encodeURIComponent(link)}`);
    return true;
  } catch {
    return false;
  }
}

export function ReferralLink({ data, isLoading, error }: ReferralLinkProps): ReactElement {
  const [copied, setCopied] = useState(false);

  if (error) {
    return (
      <Card title="Реферальная ссылка">
        <p className="text-sm text-tg-destructive" data-testid="referral-error">
          Не удалось загрузить реферальные данные: {error.message}
        </p>
      </Card>
    );
  }

  if (isLoading || !data) {
    return (
      <Card title="Реферальная ссылка">
        <p className="text-sm text-tg-hint" data-testid="referral-loading">
          Загружаем…
        </p>
      </Card>
    );
  }

  const onCopy = async (): Promise<void> => {
    const ok = await copyToClipboard(data.referral_link);
    if (ok) {
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    }
  };

  return (
    <Card title="Реферальная ссылка">
      <p className="text-sm text-tg-hint">
        Пригласите друга по ссылке ниже — оба получите бонусные токены при его первой покупке.
      </p>
      <div className="mt-3 flex items-stretch gap-2">
        <input
          readOnly
          value={data.referral_link}
          data-testid="referral-input"
          className="min-w-0 flex-1 truncate rounded-tg border border-tg-separator bg-tg-secondary-bg px-3 py-2 text-sm text-tg-text focus:outline-none"
          onClick={(e) => (e.currentTarget as HTMLInputElement).select()}
        />
        <Button
          variant="secondary"
          onClick={onCopy}
          data-testid="referral-copy"
          aria-label="Скопировать реферальную ссылку"
        >
          {copied ? "Скопировано" : "Копировать"}
        </Button>
      </div>
      <div className="mt-2 flex items-center justify-between text-xs text-tg-hint">
        <span>
          Код: <span className="font-medium text-tg-text">{data.referral_code}</span>
        </span>
        <Button
          variant="ghost"
          onClick={() => shareViaTelegram(data.referral_link)}
          data-testid="referral-share"
        >
          Поделиться
        </Button>
      </div>
    </Card>
  );
}
