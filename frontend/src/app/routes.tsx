import type { RouteObject } from "react-router";

import { AppShell } from "@/components/layout/AppShell";
import { AiProvidersPage } from "@/features/ai-providers/AiProvidersPage";
import { GuestOnly, RequireAuth, SessionGate } from "@/features/auth/guards";
import { LoginPage } from "@/features/auth/LoginPage";
import { RegisterPage } from "@/features/auth/RegisterPage";
import { DashboardPage } from "@/features/dashboard/DashboardPage";
import { ExecutionPage } from "@/features/executions/ExecutionPage";
import { ExecutionsPage } from "@/features/executions/ExecutionsPage";
import { NotFoundPage } from "@/features/not-found/NotFoundPage";
import { PlannedPage } from "@/features/planned/PlannedPage";
import { EnvironmentsTab } from "@/features/projects/EnvironmentsTab";
import { ProjectLayout } from "@/features/projects/ProjectLayout";
import { ProjectRunsTab } from "@/features/projects/ProjectRunsTab";
import { ProjectsPage } from "@/features/projects/ProjectsPage";
import { SettingsTab } from "@/features/projects/SettingsTab";
import { TestsTab } from "@/features/projects/TestsTab";
import { SettingsPage } from "@/features/settings/SettingsPage";

import { NAV_ITEMS } from "./navigation";

const plannedRoutes: RouteObject[] = NAV_ITEMS.filter((item) => item.status === "planned").map((item) => ({
  path: item.path.slice(1),
  element: <PlannedPage item={item} />,
}));

export const routes: RouteObject[] = [
  {
    element: <SessionGate />,
    children: [
      {
        element: <GuestOnly />,
        children: [
          { path: "/login", element: <LoginPage /> },
          { path: "/register", element: <RegisterPage /> },
        ],
      },
      {
        element: <RequireAuth />,
        children: [
          {
            path: "/",
            element: <AppShell />,
            children: [
              { index: true, element: <DashboardPage /> },
              { path: "projects", element: <ProjectsPage /> },
              {
                path: "projects/:projectId",
                element: <ProjectLayout />,
                children: [
                  { index: true, element: <TestsTab /> },
                  { path: "tests/:caseId", element: <TestsTab /> },
                  { path: "runs", element: <ProjectRunsTab /> },
                  { path: "environments", element: <EnvironmentsTab /> },
                  { path: "settings", element: <SettingsTab /> },
                ],
              },
              { path: "executions", element: <ExecutionsPage /> },
              { path: "executions/:executionId", element: <ExecutionPage /> },
              { path: "ai-providers", element: <AiProvidersPage /> },
              { path: "settings", element: <SettingsPage /> },
              ...plannedRoutes,
              { path: "*", element: <NotFoundPage /> },
            ],
          },
        ],
      },
    ],
  },
];
