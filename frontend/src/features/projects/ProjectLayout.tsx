import { ExternalLink } from "lucide-react";
import { NavLink, Outlet, useLocation, useParams } from "react-router";

import { ErrorState } from "@/components/common/ErrorState";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

import { useProject } from "./api";

const TABS = [
  ["", "Tests"],
  ["runs", "Runs"],
  ["environments", "Environments and test data"],
  ["settings", "Settings"],
] as const;

export function ProjectLayout() {
  const { projectId = "" } = useParams();
  const project = useProject(projectId);
  const { pathname } = useLocation();
  const section = pathname.split("/")[3] ?? "";

  if (project.isPending) return <Skeleton className="mx-auto h-24 max-w-6xl rounded-panel" />;
  if (project.error) {
    return (
      <div className="mx-auto max-w-3xl">
        <ErrorState error={project.error} title="This project could not be opened" onRetry={() => void project.refetch()} />
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-7xl">
      <header className="pb-5">
        <p className="text-[13px] text-faint">
          <NavLink to="/projects" className="hover:text-text">
            Projects
          </NavLink>
        </p>
        <h1 className="mt-1 text-[26px] font-semibold">{project.data.name}</h1>
        <a
          href={project.data.base_url}
          target="_blank"
          rel="noreferrer noopener"
          className="mt-1 inline-flex items-center gap-1.5 font-mono text-[13px] text-muted hover:text-text"
        >
          {project.data.base_url} <ExternalLink className="size-3.5" aria-hidden />
        </a>
      </header>
      <nav aria-label="Project sections" className="mb-6 flex gap-1 overflow-x-auto border-b border-border">
        {TABS.map(([path, label]) => {
          // "Tests" covers the project root and every /tests/:caseId page.
          const active = path ? section === path : section === "" || section === "tests";
          return (
            <NavLink
              key={path}
              to={path ? `/projects/${projectId}/${path}` : `/projects/${projectId}`}
              aria-current={active ? "page" : undefined}
              className={cn(
                "-mb-px border-b-2 px-3 py-2.5 text-sm whitespace-nowrap transition-colors",
                active ? "border-beacon text-text" : "border-transparent text-muted hover:text-text",
              )}
            >
              {label}
            </NavLink>
          );
        })}
      </nav>
      <Outlet context={project.data} />
    </div>
  );
}
