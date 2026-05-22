import { beforeEach, describe, expect, it } from "vitest";

import { SETTINGS_STORAGE_KEY, useSettingsStore } from "@/store/useSettingsStore";

describe("useSettingsStore", () => {
  beforeEach(() => {
    window.localStorage.clear();
    useSettingsStore.getState().reset();
  });

  it("starts with sensible defaults", () => {
    const state = useSettingsStore.getState();
    expect(state.language).toBe("auto");
    expect(state.notificationsEnabled).toBe(true);
    expect(state.aiResponseSize).toBe("medium");
  });

  it("updates and persists user preferences", () => {
    const store = useSettingsStore.getState();
    store.setLanguage("ru");
    store.setNotificationsEnabled(false);
    store.setAiResponseSize("long");

    const state = useSettingsStore.getState();
    expect(state.language).toBe("ru");
    expect(state.notificationsEnabled).toBe(false);
    expect(state.aiResponseSize).toBe("long");

    const raw = window.localStorage.getItem(SETTINGS_STORAGE_KEY);
    expect(raw).toBeTruthy();
    const parsed = JSON.parse(raw ?? "{}") as { state: Record<string, unknown> };
    expect(parsed.state.language).toBe("ru");
    expect(parsed.state.notificationsEnabled).toBe(false);
    expect(parsed.state.aiResponseSize).toBe("long");
  });

  it("reset() restores defaults", () => {
    const store = useSettingsStore.getState();
    store.setLanguage("en");
    store.setNotificationsEnabled(false);
    store.reset();

    const state = useSettingsStore.getState();
    expect(state.language).toBe("auto");
    expect(state.notificationsEnabled).toBe(true);
  });
});
