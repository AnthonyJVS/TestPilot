import { KeyRound, LogIn, LogOut, ShieldAlert, ShieldX, UserPlus, type LucideIcon } from "lucide-react";

import type { AuditLogEntry } from "@/types/api";

export interface AuditDescription {
  icon: LucideIcon;
  tone: string;
  label: string;
}

/** Plain-language description of an audit log entry. */
export function describeAuditEntry(entry: AuditLogEntry): AuditDescription {
  const reason = (entry.details as { reason?: string }).reason;
  switch (`${entry.action}:${entry.outcome}`) {
    case "auth.register:success":
      return { icon: UserPlus, tone: "text-completed", label: "Account created" };
    case "auth.login:success":
      return { icon: LogIn, tone: "text-completed", label: "Signed in" };
    case "auth.login:failure":
      return {
        icon: ShieldX,
        tone: "text-failed",
        label: reason === "inactive" ? "Sign-in blocked: account inactive" : "Failed sign-in: wrong password",
      };
    case "auth.login:denied":
      return { icon: ShieldAlert, tone: "text-warning", label: "Sign-in paused after repeated failures" };
    case "auth.logout:success":
      return { icon: LogOut, tone: "text-muted", label: "Signed out" };
    case "auth.refresh:denied":
      return {
        icon: ShieldAlert,
        tone: "text-failed",
        label: "Session revoked: an old sign-in token was reused",
      };
    default:
      return { icon: KeyRound, tone: "text-muted", label: `${entry.action} (${entry.outcome})` };
  }
}
