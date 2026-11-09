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
    status: "available",
    summary:
      "One project per website you test, with environments such as staging and production.",
  },
  {
    path: "/workflows",
    label: "Workflow Studio",
    icon: Workflow,
    status: "available",
    summary: "Design test pipelines by connecting AI, browser, logic and data nodes.",
  },
  {
    path: "/executions",
    label: "Executions",
    icon: MonitorPlay,
    status: "available",
    summary: "Watch runs live and inspect every step afterwards.",
  },
  {
    path: "/ai-providers",
    label: "AI Providers",
    icon: Bot,
    status: "available",
    summary: "Connect one AI provider or several, and choose which model handles each task.",
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
