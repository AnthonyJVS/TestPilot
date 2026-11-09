import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { errorBody, json, mockFetch, renderApp, systemStatus, tokenResponse } from "@/test/utils";

const noAudit = (url: string) => (url.startsWith("/api/v1/audit-logs") ? json(200, { items: [], next_cursor: null }) : undefined);
const status = (url: string) => (url === "/api/v1/system/status" ? json(200, systemStatus) : undefined);

describe("authentication flow", () => {
  it("redirects anonymous visitors to sign-in", async () => {
    mockFetch((url) =>
      url === "/api/v1/auth/refresh" ? json(401, errorBody("auth.refresh_invalid", "Expired")) : undefined,
    );
    const { router } = renderApp("/executions");
    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/login");
  });

  it("restores the session from the refresh cookie and shows the dashboard", async () => {
    mockFetch(
      (url) => (url === "/api/v1/auth/refresh" ? json(200, tokenResponse()) : undefined),
      status,
      noAudit,
    );
    renderApp("/");
    expect(await screen.findByRole("heading", { name: "Dashboard" })).toBeInTheDocument();
    expect(await screen.findByText("rev 0001")).toBeInTheDocument();
    expect(screen.getByText("PostgreSQL")).toBeInTheDocument();
  });

  it("validates the sign-in form before calling the API", async () => {
    const fetchMock = mockFetch((url) =>
      url === "/api/v1/auth/refresh" ? json(401, errorBody("auth.refresh_invalid", "Expired")) : undefined,
    );
    renderApp("/login");
    await userEvent.click(await screen.findByRole("button", { name: "Sign in" }));
    expect(await screen.findByText("Enter a valid email address.")).toBeInTheDocument();
    expect(screen.getByText("Enter your password.")).toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([url]) => url === "/api/v1/auth/login")).toBe(false);
  });

  it("signs in and lands on the page the user asked for", async () => {
    mockFetch(
      (url) => (url === "/api/v1/auth/refresh" ? json(401, errorBody("auth.refresh_invalid", "Expired")) : undefined),
      (url) => (url === "/api/v1/auth/login" ? json(200, tokenResponse()) : undefined),
      status,
      noAudit,
    );
    const { router } = renderApp("/settings");
    await userEvent.type(await screen.findByLabelText("Email"), "ada@example.com");
    await userEvent.type(screen.getByLabelText("Password"), "correct-horse-battery-staple");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByRole("heading", { name: "Settings" })).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/settings");
  });

  it("explains rate limiting in plain language", async () => {
    mockFetch(
      (url) => (url === "/api/v1/auth/refresh" ? json(401, errorBody("auth.refresh_invalid", "Expired")) : undefined),
      (url) =>
        url === "/api/v1/auth/login"
          ? json(429, errorBody("rate_limited", "Too many attempts.", { retry_after_seconds: 600 }))
          : undefined,
    );
    renderApp("/login");
    await userEvent.type(await screen.findByLabelText("Email"), "ada@example.com");
    await userEvent.type(screen.getByLabelText("Password"), "wrong");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Try again in 10 minutes.");
  });
});

describe("application shell", () => {
  it("offers every section as a working page, with no planned placeholders left", async () => {
    mockFetch(
      (url) => (url === "/api/v1/auth/refresh" ? json(200, tokenResponse()) : undefined),
      (url) => (url.startsWith("/api/v1/executions") ? json(200, []) : undefined),
      status,
      noAudit,
    );
    renderApp("/reports");

    expect(await screen.findByRole("heading", { name: "Reports" })).toBeInTheDocument();
    expect(await screen.findByText("Reports appear here when a run finishes.")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Not available yet" })).not.toBeInTheDocument();

    const nav = screen.getAllByRole("navigation", { name: "Main" })[0]!;
    expect(within(nav).queryByText("Planned")).not.toBeInTheDocument();
    for (const label of ["Dashboard", "Projects", "Workflow Studio", "Executions", "AI Providers", "Reports", "Settings"]) {
      expect(within(nav).getByRole("link", { name: new RegExp(label) })).toBeInTheDocument();
    }
  });

  it("signs out, revokes the server session and returns to sign-in", async () => {
    const fetchMock = mockFetch(
      (url) => (url === "/api/v1/auth/refresh" ? json(200, tokenResponse()) : undefined),
      (url) => (url === "/api/v1/auth/logout" ? new Response(null, { status: 204 }) : undefined),
      status,
      noAudit,
    );
    renderApp("/");
    await userEvent.click(await screen.findByRole("button", { name: /account menu/i }));
    await userEvent.click(await screen.findByRole("menuitem", { name: "Sign out" }));

    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
    await waitFor(() => expect(fetchMock.mock.calls.some(([url]) => url === "/api/v1/auth/logout")).toBe(true));
  });
});
