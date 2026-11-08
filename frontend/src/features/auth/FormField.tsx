import { useId, type ReactNode } from "react";

import { Label } from "@/components/ui/label";

export function FormField({
  label,
  error,
  hint,
  children,
}: {
  label: string;
  error?: string;
  hint?: string;
  children: (props: { id: string; "aria-invalid": boolean; "aria-describedby"?: string }) => ReactNode;
}) {
  const id = useId();
  const messageId = `${id}-message`;
  const message = error ?? hint;
  return (
    <div className="space-y-1.5">
      <Label htmlFor={id}>{label}</Label>
      {children({ id, "aria-invalid": Boolean(error), "aria-describedby": message ? messageId : undefined })}
      {message ? (
        <p id={messageId} className={error ? "text-[13px] text-failed" : "text-[13px] text-faint"}>
          {message}
        </p>
      ) : null}
    </div>
  );
}

export function FormAlert({ message }: { message: string | null }) {
  if (!message) return null;
  return (
    <p role="alert" className="rounded-control border border-failed/40 bg-failed/10 px-3 py-2 text-sm text-text">
      {message}
    </p>
  );
}
