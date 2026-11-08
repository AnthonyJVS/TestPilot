import { cn, describeUserAgent, formatDateTime, formatRelative } from "@/lib/utils";
import type { AuditLogEntry } from "@/types/api";

import { describeAuditEntry } from "./audit-labels";

export function ActivityList({ entries }: { entries: AuditLogEntry[] }) {
  return (
    <ul className="divide-y divide-border">
      {entries.map((entry) => {
        const { icon: Icon, tone, label } = describeAuditEntry(entry);
        return (
          <li key={entry.id} className="flex items-start gap-3 py-3">
            <Icon className={cn("mt-0.5 size-4 shrink-0", tone)} aria-hidden />
            <div className="min-w-0 flex-1">
              <p className="text-[14px]">{label}</p>
              <p className="truncate text-[13px] text-faint">
                {describeUserAgent(entry.user_agent)}
                {entry.ip_address ? `, ${entry.ip_address}` : ""}
              </p>
            </div>
            <time
              dateTime={entry.created_at}
              title={formatDateTime(entry.created_at)}
              className="shrink-0 text-[13px] text-faint"
            >
              {formatRelative(entry.created_at)}
            </time>
          </li>
        );
      })}
    </ul>
  );
}
