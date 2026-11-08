import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router";
import { toast } from "sonner";

import { apiRequest } from "@/lib/api-client";
import { useAuthStore } from "@/stores/auth-store";
import type { LoginRequest, RegisterRequest, TokenResponse } from "@/types/api";

export function useLogin() {
  const setSession = useAuthStore((s) => s.setSession);
  return useMutation({
    mutationFn: (body: LoginRequest) =>
      apiRequest<TokenResponse>("/auth/login", { method: "POST", body, auth: false }),
    onSuccess: setSession,
  });
}

export function useRegister() {
  const setSession = useAuthStore((s) => s.setSession);
  return useMutation({
    mutationFn: (body: RegisterRequest) =>
      apiRequest<TokenResponse>("/auth/register", { method: "POST", body, auth: false }),
    onSuccess: setSession,
  });
}

export function useLogout() {
  const clearSession = useAuthStore((s) => s.clearSession);
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  return useMutation({
    mutationFn: () => apiRequest<void>("/auth/logout", { method: "POST", auth: false, csrf: true }),
    onSettled: (_data, error) => {
      // Always drop local state; the server session is revoked when the call succeeds.
      clearSession();
      queryClient.clear();
      navigate("/login", { replace: true });
      if (error) toast.error("Signed out locally, but the server could not be reached.");
      else toast.success("Signed out");
    },
  });
}
