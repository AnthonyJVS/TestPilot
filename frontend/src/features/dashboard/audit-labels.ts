import {
  Bot,
  KeyRound,
  LogIn,
  LogOut,
  Route,
  ShieldAlert,
  ShieldX,
  UserPlus,
  type LucideIcon,
} from "lucide-react";

import type { AuditLogEntry } from "@/types/api";

function detail(entry: AuditLogEntry, key: string): string {
  const value = (entry.details as Record<string, unknown>)[key];
  return typeof value === "string" ? value : "unnamed";
}

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
    case "ai.provider.create:success":
      return { icon: Bot, tone: "text-completed", label: `AI provider added: ${detail(entry, "name")}` };
    case "ai.provider.delete:success":
      return { icon: Bot, tone: "text-muted", label: `AI provider deleted: ${detail(entry, "name")}` };
    case "ai.provider.update:success":
      return { icon: Bot, tone: "text-muted", label: "AI provider updated" };
    case "ai.provider.test:success":
      return { icon: Bot, tone: "text-completed", label: "AI provider connection verified" };
    case "ai.provider.test:failure":
      return { icon: Bot, tone: "text-failed", label: "AI provider connection test failed" };
    case "ai.credential.set:success":
    case "ai.credential.rotate:success":
      return { icon: KeyRound, tone: "text-completed", label: "AI provider key replaced" };
    case "ai.credential.delete:success":
      return { icon: KeyRound, tone: "text-muted", label: "AI provider key deleted" };
    case "ai.routing.update:success":
      return { icon: Route, tone: "text-muted", label: "AI task routing changed" };
    default:
      return { icon: KeyRound, tone: "text-muted", label: `${entry.action} (${entry.outcome})` };
  }
}
