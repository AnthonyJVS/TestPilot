import "@testing-library/jest-dom/vitest";

import { cleanup } from "@testing-library/react";
import { afterEach, vi } from "vitest";

import { useAuthStore } from "@/stores/auth-store";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  useAuthStore.setState({ status: "unknown", accessToken: null, user: null });
});
