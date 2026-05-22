import { useCallback, useMemo } from "react";

import { translate } from "@/i18n";
import type { Language, TranslationKey } from "@/i18n";
import { useSettingsStore } from "@/store/useSettingsStore";
import { useUserStore } from "@/store/useUserStore";
import { resolveLanguage } from "@/i18n";

export interface UseTranslationResult {
  language: Language;
  t: (key: TranslationKey, vars?: Record<string, string | number>) => string;
}

export function useTranslation(): UseTranslationResult {
  const preference = useSettingsStore((s) => s.language);
  const fallback = useUserStore((s) => s.user?.language_code ?? null);
  const language = useMemo(() => resolveLanguage(preference, fallback), [preference, fallback]);
  const t = useCallback(
    (key: TranslationKey, vars?: Record<string, string | number>) => translate(language, key, vars),
    [language],
  );
  return { language, t };
}
