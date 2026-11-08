import {
  Bot,
  FileText,
  FolderKanban,
  LayoutDashboard,
  MonitorPlay,
  Settings,
  Workflow,
  type LucideIcon,
} from "lucide-react";

export interface NavItem {
  path: string;
  label: string;
  icon: LucideIcon;
  /** "available" sections are built; "planned" ones show what is coming and when. */
  status: "available" | "planned";
  milestone?: number;
  summary: string;
  plannedCapabilities?: string[];
}

export const NAV_ITEMS: NavItem[] = [
  {
    path: "/",
    label: "Dashboard",
    icon: LayoutDashboard,
    status: "available",
    summary: "System status, setup progress and recent account activity.",
  },
  {
    path: "/projects",
    label: "Projects",
    icon: FolderKanban,
    status: "planned",
    milestone: 3,
    summary:
      "One project per website you test, with environments such as staging and production.",
    plannedCapabilities: [
      "Target URL, allowed domains and environments with encrypted test credentials",
      "Describe a scenario in plain language and get a structured test plan",
      "Review, edit and approve the plan before anything runs",
      "Read the Playwright code generated from the approved plan",
    ],
  },
  {
    path: "/workflows",
    label: "Workflow Studio",
    icon: Workflow,
    status: "planned",
    milestone: 5,
    summary: "Design test pipelines by connecting AI, browser, logic and data nodes.",
    plannedCapabilities: [
      "Searchable node palette with drag-and-drop onto a canvas",
      "Typed connections, conditional branches and error paths",
      "Retry and timeout policies per node",
      "Validation, saved versions and one-click runs",
    ],
  },
  {
    path: "/executions",
    label: "Executions",
    icon: MonitorPlay,
    status: "planned",
    milestone: 4,
    summary: "Watch runs live and inspect every step afterwards.",
    plannedCapabilities: [
      "Live node states on the workflow canvas",
      "Timeline of AI, browser and system events with filters",
      "Inspector showing redacted AI requests and responses",
      "Browser preview built from real screenshots of the run",
    ],
  },
  {
    path: "/ai-providers",
    label: "AI Providers",
    icon: Bot,
    status: "planned",
    milestone: 2,
    summary: "Connect one AI provider or several, and choose which model handles each task.",
    plannedCapabilities: [
      "Simple mode: one key (for example Gemini) powers every AI task",
      "Advanced mode: a different provider and model per task",
      "Connection tests, model discovery and manual model IDs",
      "Keys encrypted at rest and never shown again after saving",
    ],
  },
  {
    path: "/reports",
    label: "Reports",
    icon: FileText,
    status: "planned",
    milestone: 8,
    summary: "Shareable HTML reports for every run.",
    plannedCapabilities: [
      "Pass, fail and skip summary with durations",
      "Screenshots, logs and artifacts",
      "Failure analysis that separates evidence from AI hypotheses",
      "The provider and model used for each AI task",
    ],
  },
  {
    path: "/settings",
    label: "Settings",
    icon: Settings,
    status: "available",
    summary: "Profile, appearance and account security activity.",
  },
];

export function findNavItem(path: string): NavItem | undefined {
  return NAV_ITEMS.find((item) => item.path === path);
}
