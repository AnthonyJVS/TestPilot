import { Moon, Sun } from "lucide-react";
import type { ReactNode } from "react";

import { ErrorState } from "@/components/common/ErrorState";
import { PageHeader } from "@/components/common/PageHeader";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { ActivityList } from "@/features/dashboard/ActivityList";
import { useAuditLogs } from "@/features/dashboard/api";
import { cn, formatDateTime } from "@/lib/utils";
import { useAuthStore } from "@/stores/auth-store";
import { useThemeStore, type Theme } from "@/stores/theme-store";

function SettingsSection({ id, title, description, children }: {
  id: string;
  title: string;
  description: string;
  children: ReactNode;
}) {
  return (
    <section aria-labelledby={id} className="grid gap-4 border-t border-border py-8 md:grid-cols-3">
      <div>
        <h2 id={id} className="text-[15px] font-semibold">
          {title}
        </h2>
        <p className="mt-1 text-[13px] text-muted">{description}</p>
      </div>
      <div className="md:col-span-2">{children}</div>
    </section>
  );
}

function ThemeOption({ value, icon, label }: { value: Theme; icon: ReactNode; label: string }) {
  const { theme, setTheme } = useThemeStore();
  const selected = theme === value;
  return (
    <button
      type="button"
      role="radio"
      aria-checked={selected}
      onClick={() => setTheme(value)}
      className={cn(
        "flex flex-1 items-center gap-3 rounded-panel border px-4 py-3 text-left transition-colors",
        selected ? "border-beacon bg-beacon-soft" : "border-border-strong hover:bg-raised",
      )}
    >
      {icon}
      <span className="font-medium">{label}</span>
    </button>
  );
}

function SecurityActivity() {
  const { data, error, isPending, refetch, hasNextPage, fetchNextPage, isFetchingNextPage } = useAuditLogs(20);
  if (isPending) return <Skeleton className="h-40" />;
  if (error) return <ErrorState error={error} onRetry={() => void refetch()} />;
  const entries = data.pages.flatMap((p) => p.items);
  return (
    <div className="rounded-panel border border-border bg-panel px-5">
      {entries.length ? <ActivityList entries={entries} /> : <p className="py-6 text-sm text-muted">No activity yet.</p>}
      {hasNextPage ? (
        <div className="border-t border-border py-3">
          <Button variant="ghost" size="sm" onClick={() => void fetchNextPage()} disabled={isFetchingNextPage}>
            {isFetchingNextPage ? "Loading…" : "Show older activity"}
          </Button>
        </div>
      ) : null}
    </div>
  );
}

export function SettingsPage() {
  const user = useAuthStore((s) => s.user);
  if (!user) return null;
  return (
    <div className="mx-auto max-w-4xl">
      <PageHeader title="Settings" description="Your profile, how TestPilot looks, and who has used your account." />

      <SettingsSection id="profile-heading" title="Profile" description="Editing your name and email arrives with account management.">
        <dl className="grid gap-x-6 gap-y-4 sm:grid-cols-2">
          <div>
            <dt className="text-[13px] text-muted">Name</dt>
            <dd className="mt-0.5">{user.display_name}</dd>
          </div>
          <div>
            <dt className="text-[13px] text-muted">Email</dt>
            <dd className="mt-0.5 break-all">{user.email}</dd>
          </div>
          <div>
            <dt className="text-[13px] text-muted">Member since</dt>
            <dd className="mt-0.5">{formatDateTime(user.created_at)}</dd>
          </div>
          <div>
            <dt className="text-[13px] text-muted">Last sign-in</dt>
            <dd className="mt-0.5">{user.last_login_at ? formatDateTime(user.last_login_at) : "Never"}</dd>
          </div>
        </dl>
      </SettingsSection>

      <SettingsSection id="appearance-heading" title="Appearance" description="Saved in this browser only.">
        <div role="radiogroup" aria-labelledby="appearance-heading" className="flex flex-col gap-3 sm:flex-row">
          <ThemeOption value="dark" icon={<Moon className="size-4 text-muted" aria-hidden />} label="Dark" />
          <ThemeOption value="light" icon={<Sun className="size-4 text-muted" aria-hidden />} label="Light" />
        </div>
      </SettingsSection>

      <SettingsSection
        id="security-heading"
        title="Security activity"
        description="Sign-ins, failed attempts and revoked sessions for your account, newest first."
      >
        <SecurityActivity />
      </SettingsSection>
    </div>
  );
}
