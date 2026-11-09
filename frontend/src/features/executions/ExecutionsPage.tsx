import { PageHeader } from "@/components/common/PageHeader";

import { ExecutionsList } from "./ExecutionsList";

export function ExecutionsPage() {
  return (
    <div className="mx-auto max-w-6xl">
      <PageHeader
        title="Executions"
        description="Every test run with its live steps, browser screenshots, console and network evidence, and artifacts."
      />
      <ExecutionsList limit={100} emptyHint="No runs yet. Open a test with an approved plan and choose Run test." />
    </div>
  );
}
