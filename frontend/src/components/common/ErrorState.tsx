import { CircleAlert } from "lucide-react";

import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api-client";

export function ErrorState({
  error,
  title = "This section could not load",
  onRetry,
}: {
  error: unknown;
  title?: string;
  onRetry?: () => void;
}) {
  const message = error instanceof Error ? error.message : "Something went wrong.";
  const requestId = error instanceof ApiError ? error.requestId : null;
  return (
    <div role="alert" className="flex items-start gap-3 rounded-panel border border-failed/40 bg-failed/5 p-4">
      <CircleAlert className="mt-0.5 size-5 shrink-0 text-failed" aria-hidden />
      <div className="min-w-0 flex-1">
        <p className="font-medium">{title}</p>
        <p className="mt-0.5 text-sm text-muted">{message}</p>
        {requestId ? (
          <p className="mt-1 text-xs text-faint">
            Request ID <code className="font-mono">{requestId}</code>
          </p>
        ) : null}
      </div>
      {onRetry ? (
        <Button variant="secondary" size="sm" onClick={onRetry}>
          Try again
        </Button>
      ) : null}
    </div>
  );
}
