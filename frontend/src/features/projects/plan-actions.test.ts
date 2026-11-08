import { describe, expect, it } from "vitest";

import type { PlanStep } from "@/types/api";

import { blankStep, normalizeStep } from "./plan-actions";

describe("normalizeStep", () => {
  it("drops an empty locator left over when switching to an action where it is optional", () => {
    const click = blankStep("click");
    expect(click.locator).not.toBeNull();
    const press = normalizeStep({ ...click, action: "press" });
    expect(press.locator).toBeNull();
    expect(press.value).toBe("");
  });

  it("keeps a filled-in locator for optional-locator actions", () => {
    const step: PlanStep = {
      action: "click",
      description: "x",
      locator: { strategy: "label", value: "Search", role: null, exact: false, nth: null },
      value: null,
    };
    expect(normalizeStep({ ...step, action: "press" }).locator?.value).toBe("Search");
  });

  it("removes fields the new action does not use", () => {
    const expectText: PlanStep = {
      action: "expect_text",
      description: "x",
      locator: { strategy: "text", value: "Hi", role: null, exact: false, nth: null },
      value: "Hello",
      match: "exact",
    };
    const url = normalizeStep({ ...expectText, action: "expect_url" });
    expect(url.locator).toBeNull();
    expect(url.match).toBe("exact");
    const click = normalizeStep({ ...expectText, action: "click" });
    expect(click.value).toBeNull();
    expect(click.match).toBeNull();
  });
});
