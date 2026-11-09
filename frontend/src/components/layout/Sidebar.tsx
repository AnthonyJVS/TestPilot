import { NavLink } from "react-router";

import { NAV_ITEMS } from "@/app/navigation";
import { Logo } from "@/components/common/Logo";
import { cn } from "@/lib/utils";

export function SidebarNav({ onNavigate }: { onNavigate?: () => void }) {
  return (
    <nav aria-label="Main" className="flex flex-col gap-0.5 px-3">
      {NAV_ITEMS.map((item) => {
        const Icon = item.icon;
        return (
          <NavLink
            key={item.path}
            to={item.path}
            end={item.path === "/"}
            onClick={onNavigate}
            className={({ isActive }) =>
              cn(
                "group relative flex items-center gap-3 rounded-control px-3 py-2 text-[14px] transition-colors",
                isActive
                  ? "bg-raised text-text before:absolute before:inset-y-1.5 before:-left-3 before:w-[3px] before:rounded-r before:bg-beacon"
                  : "text-muted hover:bg-raised/60 hover:text-text",
              )
            }
          >
            <Icon className="size-[18px] shrink-0" aria-hidden />
            <span className="flex-1">{item.label}</span>
            {item.status === "planned" ? (
              <span className="text-[11px] text-faint" title={`Planned for milestone ${item.milestone}`}>
                Planned
              </span>
            ) : null}
          </NavLink>
        );
      })}
    </nav>
  );
}

export function Sidebar() {
  return (
    <aside className="hidden w-60 shrink-0 flex-col border-r border-border bg-panel lg:flex">
      <div className="flex h-16 items-center px-6">
        <Logo />
      </div>
      <div className="flex-1 overflow-y-auto py-2">
        <SidebarNav />
      </div>
      <p className="border-t border-border px-6 py-4 text-xs text-faint">
        TestPilot v1
      </p>
    </aside>
  );
}
