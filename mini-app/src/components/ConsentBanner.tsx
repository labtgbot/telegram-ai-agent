import type { ReactElement } from "react";
import { useTranslation } from "@/i18n/useTranslation";
import { useConsentStore, consentNeedsDecision } from "@/store/useConsentStore";

/**
 * GDPR-style consent banner shown on first launch (and after a banner-version
 * bump). The Mini App uses local storage and optional analytics; the user
 * picks "Accept all" (analytics on) or "Necessary only" (functional only).
 *
 * The banner is dismissed by recording a decision in `useConsentStore`,
 * which `partialize`s to a single key in `localStorage` so the decision
 * survives reloads.
 */
export function ConsentBanner(): ReactElement | null {
  const { t } = useTranslation();
  const record = useConsentStore((s) => s.record);
  const setDecision = useConsentStore((s) => s.setDecision);

  if (!consentNeedsDecision(record)) {
    return null;
  }

  return (
    <div
      role="dialog"
      aria-modal="false"
      aria-labelledby="consent-banner-title"
      data-testid="consent-banner"
      className="fixed inset-x-0 bottom-0 z-50 mx-auto max-w-md p-3"
    >
      <div className="rounded-tg bg-tg-section-bg p-4 shadow-tg ring-1 ring-tg-divider/40">
        <h2 id="consent-banner-title" className="text-base font-semibold text-tg-text">
          {t("consent.title")}
        </h2>
        <p className="mt-2 text-sm text-tg-hint">{t("consent.body")}</p>
        <p className="mt-2 text-xs text-tg-hint">
          {t("consent.learnMore")}{" "}
          <a
            className="text-tg-link underline"
            href="/privacy"
            target="_blank"
            rel="noreferrer noopener"
          >
            {t("consent.privacyLink")}
          </a>
          {" · "}
          <a
            className="text-tg-link underline"
            href="/terms"
            target="_blank"
            rel="noreferrer noopener"
          >
            {t("consent.termsLink")}
          </a>
        </p>
        <div className="mt-4 flex flex-col gap-2 sm:flex-row sm:justify-end">
          <button
            type="button"
            data-testid="consent-necessary"
            onClick={() => setDecision("necessary")}
            className="inline-flex items-center justify-center rounded-tg bg-tg-secondary-bg px-4 py-2 text-sm font-medium text-tg-text transition-opacity hover:opacity-90 focus:outline-none focus:ring-2 focus:ring-tg-accent"
          >
            {t("consent.necessaryOnly")}
          </button>
          <button
            type="button"
            data-testid="consent-accept"
            onClick={() => setDecision("accepted")}
            className="inline-flex items-center justify-center rounded-tg bg-tg-button px-4 py-2 text-sm font-medium text-tg-button-text transition-opacity hover:opacity-90 focus:outline-none focus:ring-2 focus:ring-tg-accent"
          >
            {t("consent.acceptAll")}
          </button>
        </div>
      </div>
    </div>
  );
}
