import { en } from "@/i18n/locales/en";
import { ru } from "@/i18n/locales/ru";
import type { TranslationDict } from "@/i18n/locales/en";

export type Language = "en" | "ru";
export type LanguagePreference = Language | "auto";

const DICTS: Record<Language, TranslationDict> = { en, ru };

type Leaves<T> = T extends string
  ? ""
  : {
      [K in keyof T & string]: T[K] extends string ? K : `${K}.${Leaves<T[K]>}`;
    }[keyof T & string];

export type TranslationKey = Leaves<TranslationDict>;

/** Resolve a Telegram `language_code` (e.g. "ru", "en-US") to a supported language. */
export function resolveLanguage(
  preference: LanguagePreference,
  fallback: string | null | undefined,
): Language {
  if (preference === "ru" || preference === "en") return preference;
  if (!fallback) return "en";
  const normalized = fallback.toLowerCase();
  if (normalized.startsWith("ru")) return "ru";
  return "en";
}

function getByPath(dict: TranslationDict, key: string): string {
  const parts = key.split(".");
  let cursor: unknown = dict;
  for (const part of parts) {
    if (cursor && typeof cursor === "object" && part in (cursor as object)) {
      cursor = (cursor as Record<string, unknown>)[part];
    } else {
      return key;
    }
  }
  return typeof cursor === "string" ? cursor : key;
}

function format(template: string, vars: Record<string, string | number>): string {
  return template.replace(/\{(\w+)\}/g, (_, name: string) =>
    name in vars ? String(vars[name]) : `{${name}}`,
  );
}

export function translate(
  language: Language,
  key: TranslationKey,
  vars?: Record<string, string | number>,
): string {
  const value = getByPath(DICTS[language], key);
  return vars ? format(value, vars) : value;
}

export const dictionaries = DICTS;
