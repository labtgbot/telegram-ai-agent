import { beforeEach, describe, expect, it } from "vitest";

import { useUserStore } from "@/store/useUserStore";

describe("useUserStore", () => {
  beforeEach(() => {
    useUserStore.getState().reset();
  });

  it("starts with empty state", () => {
    const state = useUserStore.getState();
    expect(state.user).toBeNull();
    expect(state.balance).toBeNull();
    expect(state.isLoading).toBe(false);
    expect(state.error).toBeNull();
  });

  it("updates user, balance, loading, error fields", () => {
    const store = useUserStore.getState();
    store.setUser({
      id: 1,
      telegram_id: 42,
      username: "alice",
      first_name: "Alice",
      last_name: null,
      language_code: "en",
      role: "user",
      referral_code: "ref-1",
      is_premium: false,
      is_banned: false,
    });
    store.setBalance(150);
    store.setLoading(true);
    store.setError("oops");

    const state = useUserStore.getState();
    expect(state.user?.username).toBe("alice");
    expect(state.balance).toBe(150);
    expect(state.isLoading).toBe(true);
    expect(state.error).toBe("oops");
  });

  it("reset() clears all fields", () => {
    const store = useUserStore.getState();
    store.setBalance(99);
    store.setError("err");
    store.reset();

    const state = useUserStore.getState();
    expect(state.balance).toBeNull();
    expect(state.error).toBeNull();
  });
});
