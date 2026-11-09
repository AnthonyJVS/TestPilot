import { Database, FlaskConical, GitBranch, Globe, Sparkles, type LucideIcon } from "lucide-react";

export const CATEGORY: Record<string, { icon: LucideIcon; tone: string; label: string }> = {
  data: { icon: Database, tone: "text-sky", label: "Data" },
  browser: { icon: Globe, tone: "text-beacon", label: "Browser" },
  test: { icon: FlaskConical, tone: "text-completed", label: "Tests" },
  ai: { icon: Sparkles, tone: "text-running", label: "AI" },
  logic: { icon: GitBranch, tone: "text-muted", label: "Logic" },
};
