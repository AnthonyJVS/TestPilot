import { useOutletContext } from "react-router";

import { ExecutionsList } from "@/features/executions/ExecutionsList";
import type { Project } from "@/types/api";

export function ProjectRunsTab() {
  const project = useOutletContext<Project>();
  return <ExecutionsList projectId={project.id} limit={100} emptyHint="No runs in this project yet. Open an approved test and choose Run test." />;
}
