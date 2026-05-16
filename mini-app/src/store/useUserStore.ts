import { create } from "zustand";

export interface User {
  id: number;
  telegram_id: number;
  username: string | null;
  first_name: string | null;
  last_name: string | null;
  language_code: string | null;
  role: string;
  referral_code: string;
  is_premium: boolean;
  is_banned: boolean;
}

interface UserState {
  user: User | null;
  balance: number | null;
  isLoading: boolean;
  error: string | null;
  setUser: (user: User | null) => void;
  setBalance: (balance: number | null) => void;
  setLoading: (loading: boolean) => void;
  setError: (error: string | null) => void;
  reset: () => void;
}

const INITIAL: Omit<UserState, "setUser" | "setBalance" | "setLoading" | "setError" | "reset"> = {
  user: null,
  balance: null,
  isLoading: false,
  error: null,
};

export const useUserStore = create<UserState>((set) => ({
  ...INITIAL,
  setUser: (user) => set({ user }),
  setBalance: (balance) => set({ balance }),
  setLoading: (isLoading) => set({ isLoading }),
  setError: (error) => set({ error }),
  reset: () => set({ ...INITIAL }),
}));
