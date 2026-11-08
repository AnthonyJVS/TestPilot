import type { PlanStep, TestPlan } from "@/types/api";

export type Action = PlanStep["action"];

interface ActionMeta {
  label: string;
  locator: "required" | "optional" | "none";
  value: string | null; // label of the value field, null when the action takes no value
  valueHint?: string;
  match?: boolean;
  state?: boolean;
}

/** Mirrors the backend DSL rules in app/domain/test_plan.py (the server stays authoritative). */
export const ACTIONS: Record<Action, ActionMeta> = {
  goto: { label: "Open page", locator: "none", value: "Path or URL", valueHint: "/login" },
  click: { label: "Click", locator: "required", value: null },
  fill: { label: "Fill in", locator: "required", value: "Text", valueHint: "{{env.LOGIN_EMAIL}}" },
  select_option: { label: "Select option", locator: "required", value: "Option" },
  check: { label: "Check", locator: "required", value: null },
  uncheck: { label: "Uncheck", locator: "required", value: null },
  press: { label: "Press key", locator: "optional", value: "Key", valueHint: "Enter" },
  wait_for: { label: "Wait for", locator: "required", value: null, state: true },
  expect_visible: { label: "Expect visible", locator: "required", value: null },
  expect_hidden: { label: "Expect hidden", locator: "required", value: null },
  expect_text: { label: "Expect text", locator: "required", value: "Expected text", match: true },
  expect_url: { label: "Expect URL", locator: "none", value: "URL contains", valueHint: "/dashboard", match: true },
  expect_title: { label: "Expect title", locator: "none", value: "Title", match: true },
  screenshot: { label: "Screenshot", locator: "none", value: "Name", valueHint: "after-login" },
};

export const STRATEGIES = [
  ["role", "Role and name"],
  ["label", "Label"],
  ["text", "Text"],
  ["placeholder", "Placeholder"],
  ["test_id", "Test ID"],
  ["css", "CSS selector"],
] as const;

export const ROLES = [
  "button",
  "link",
  "textbox",
  "checkbox",
  "radio",
  "combobox",
  "listbox",
  "option",
  "heading",
  "img",
  "dialog",
  "alert",
  "tab",
  "tabpanel",
  "menu",
  "menuitem",
  "navigation",
  "main",
  "row",
  "cell",
  "table",
  "list",
  "listitem",
  "searchbox",
  "switch",
  "slider",
  "spinbutton",
  "form",
  "region",
  "banner",
  "article",
  "paragraph",
  "status",
  "progressbar",
] as const;

/** Keep only the fields the chosen action uses, so switching actions never leaves invalid leftovers. */
export function normalizeStep(step: PlanStep): PlanStep {
  const meta = ACTIONS[step.action];
  let locator = step.locator ?? null;
  if (meta.locator === "none") locator = null;
  // An optional locator left over from another action (e.g. Click -> Press key) is dropped unless filled in.
  else if (meta.locator === "optional" && !locator?.value.trim()) locator = null;
  else if (meta.locator === "required" && !locator) locator = { strategy: "role", role: "button", value: "", exact: false };
  return {
    action: step.action,
    description: step.description,
    locator,
    value: meta.value ? (step.value ?? "") : null,
    match: meta.match ? (step.match ?? null) : null,
    state: meta.state ? (step.state ?? null) : null,
    timeout_ms: step.timeout_ms ?? null,
  };
}

export function blankStep(action: Action = "click"): PlanStep {
  return normalizeStep({ action, description: "", locator: null, value: null });
}

/** Starting point when the user writes a plan without AI. */
export function emptyPlan(name: string): TestPlan {
  return {
    name,
    description: "",
    preconditions: [],
    test_data: [],
    steps: [{ ...blankStep("goto"), description: "Open the start page", value: "/" }],
    expected_results: [],
    cleanup: [],
  };
}
