import { useEffect, useState } from "react";
import { Navigate, Outlet, useLocation } from "react-router";

import { ErrorState } from "@/components/common/ErrorState";
import { LogoMark } from "@/components/common/Logo";
import { refreshSession } from "@/lib/api-client";
import { useAuthStore } from "@/stores/auth-store";

/**
 * Restores the session on page load by exchanging the HttpOnly refresh cookie for an
 * in-memory access token. Renders children once the auth status is known.
 */
export function SessionGate() {
  const status = useAuthStore((s) => s.status);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    if (useAuthStore.getState().status === "unknown") refreshSession().catch(setError);
  }, []);

  const retry = () => {
    setError(null);
    refreshSession().catch(setError);
  };

  if (error && status === "unknown") {
    return (
      <div className="mx-auto grid min-h-dvh max-w-lg place-items-center px-4">
        <ErrorState error={error} title="TestPilot is not reachable" onRetry={retry} />
      </div>
    );
  }
  if (status === "unknown") {
    return (
      <div className="grid min-h-dvh place-items-center" role="status" aria-label="Restoring your session">
        <LogoMark className="size-10 animate-pulse" />
      </div>
    );
  }
  return <Outlet />;
}

export function RequireAuth() {
  const status = useAuthStore((s) => s.status);
  const location = useLocation();
  if (status !== "authenticated") {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  }
  return <Outlet />;
}

/** Sign-in pages. Once authenticated, send the user back to where they were going. */
export function GuestOnly() {
  const status = useAuthStore((s) => s.status);
  const location = useLocation();
  if (status === "authenticated") {
    const from = (location.state as { from?: string } | null)?.from;
    return <Navigate to={from && from.startsWith("/") && !from.startsWith("//") ? from : "/"} replace />;
  }
  return <Outlet />;
}
