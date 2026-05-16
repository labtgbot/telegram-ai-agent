import { create } from "zustand";
import { persist, createJSONStorage } from "zustand/middleware";

export type ConsentDecision = "accepted" | "necessary";

export interface ConsentRecord {
  decision: ConsentDecision;
  /** ISO timestamp of the moment the user made the decision. */
  decidedAt: string;
  /** Banner version the decision applies to — bumped on material updates. */
  version: number;
}

export interface ConsentState {
  record: ConsentRecord | null;
  setDecision: (decision: ConsentDecision) => void;
  reset: () => void;
}

/**
 * Increment this when the cookie / privacy notice changes substantially so
 * existing decisions are re-collected.
 */
export const CONSENT_VERSION = 1;

export const CONSENT_STORAGE_KEY = "tg-ai-agent.consent";

export const useConsentStore = create<ConsentState>()(
  persist(
    (set) => ({
      record: null,
      setDecision: (decision) =>
        set({
          record: {
            decision,
            decidedAt: new Date().toISOString(),
            version: CONSENT_VERSION,
          },
        }),
      reset: () => set({ record: null }),
    }),
    {
      name: CONSENT_STORAGE_KEY,
      storage: createJSONStorage(() => {
        if (typeof window !== "undefined" && window.localStorage) {
          return window.localStorage;
        }
        return memoryStorage();
      }),
      version: 1,
      partialize: (state) => ({ record: state.record }),
    },
  ),
);

/** True when the user must still make a consent decision. */
export function consentNeedsDecision(record: ConsentRecord | null): boolean {
  if (!record) return true;
  return record.version < CONSENT_VERSION;
}

function memoryStorage(): Storage {
  const map = new Map<string, string>();
  return {
    get length() {
      return map.size;
    },
    clear: () => map.clear(),
    getItem: (key) => map.get(key) ?? null,
    key: (index) => Array.from(map.keys())[index] ?? null,
    removeItem: (key) => {
      map.delete(key);
    },
    setItem: (key, value) => {
      map.set(key, value);
    },
  };
}
