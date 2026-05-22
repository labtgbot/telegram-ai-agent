import { beforeEach, describe, expect, it } from "vitest";

import {
  CONSENT_STORAGE_KEY,
  CONSENT_VERSION,
  consentNeedsDecision,
  useConsentStore,
} from "@/store/useConsentStore";

describe("useConsentStore", () => {
  beforeEach(() => {
    window.localStorage.clear();
    useConsentStore.getState().reset();
  });

  it("starts with no recorded decision", () => {
    expect(useConsentStore.getState().record).toBeNull();
    expect(consentNeedsDecision(null)).toBe(true);
  });

  it("persists a decision to localStorage with the current version", () => {
    useConsentStore.getState().setDecision("accepted");

    const record = useConsentStore.getState().record;
    expect(record?.decision).toBe("accepted");
    expect(record?.version).toBe(CONSENT_VERSION);
    expect(consentNeedsDecision(record)).toBe(false);

    const raw = window.localStorage.getItem(CONSENT_STORAGE_KEY);
    expect(raw).toBeTruthy();
    const parsed = JSON.parse(raw ?? "{}") as { state: { record: { decision: string } } };
    expect(parsed.state.record.decision).toBe("accepted");
  });

  it("treats an older banner version as needing a fresh decision", () => {
    expect(
      consentNeedsDecision({
        decision: "accepted",
        decidedAt: "2026-01-01T00:00:00.000Z",
        version: CONSENT_VERSION - 1,
      }),
    ).toBe(true);
  });

  it("reset() clears the record", () => {
    useConsentStore.getState().setDecision("necessary");
    expect(useConsentStore.getState().record).not.toBeNull();
    useConsentStore.getState().reset();
    expect(useConsentStore.getState().record).toBeNull();
  });
});
