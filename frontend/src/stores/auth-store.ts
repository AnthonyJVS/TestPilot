import { create } from "zustand";

import type { TokenResponse, User } from "@/types/api";

export type AuthStatus = "unknown" | "authenticated" | "anonymous";

interface AuthState {
  status: AuthStatus;
  /** Kept in memory only — never persisted to storage. */
  accessToken: string | null;
  user: User | null;
  setSession: (tokens: TokenResponse) => void;
  clearSession: () => void;
}

export const useAuthStore = create<AuthState>()((set) => ({
  status: "unknown",
  accessToken: null,
  user: null,
  setSession: (tokens) =>
    set({ status: "authenticated", accessToken: tokens.access_token, user: tokens.user }),
  clearSession: () => set({ status: "anonymous", accessToken: null, user: null }),
}));
