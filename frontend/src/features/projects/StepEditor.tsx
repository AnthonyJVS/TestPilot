import { ArrowDown, ArrowUp, CircleX, AlertTriangle, Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { cn } from "@/lib/utils";
import type { PlanLocator, PlanStep } from "@/types/api";

import { ACTIONS, ROLES, STRATEGIES, normalizeStep, type Action } from "./plan-actions";

export interface StepMessage {
  severity: "error" | "warning";
  message: string;
}

const fieldClass = "h-9 text-[13px]";

export function StepEditor({
  step,
  index,
  messages,
  onChange,
  onMove,
  onRemove,
  isFirst,
  isLast,
}: {
  step: PlanStep;
  index: number;
  messages: StepMessage[];
  onChange: (step: PlanStep) => void;
  onMove: (delta: -1 | 1) => void;
  onRemove: () => void;
  isFirst: boolean;
  isLast: boolean;
}) {
  const meta = ACTIONS[step.action];
  const id = `step-${index}`;
  const update = (patch: Partial<PlanStep>) => onChange({ ...step, ...patch });
  const updateLocator = (patch: Partial<PlanLocator>) => {
    const current: PlanLocator = step.locator ?? { strategy: "role", role: "button", value: "", exact: false };
    const next = { ...current, ...patch };
    if (patch.strategy && patch.strategy !== "role") next.role = null;
    if (patch.strategy === "role" && !next.role) next.role = "button";
    update({ locator: next });
  };
  const hasError = messages.some((m) => m.severity === "error");

  return (
    <li
      className={cn(
        "rounded-panel border bg-panel px-4 py-3",
        hasError ? "border-failed/50" : "border-border",
      )}
      aria-labelledby={`${id}-label`}
    >
      <div className="flex flex-wrap items-center gap-2">
        <span id={`${id}-label`} className="w-7 text-sm font-semibold tabular-nums text-faint">
          {index + 1}
          <span className="sr-only">. Step</span>
        </span>
        <NativeSelect
          aria-label={`Step ${index + 1} action`}
          value={step.action}
          onChange={(e) => onChange(normalizeStep({ ...step, action: e.target.value as Action }))}
          className="w-40"
        >
          {Object.entries(ACTIONS).map(([value, a]) => (
            <option key={value} value={value}>
              {a.label}
            </option>
          ))}
        </NativeSelect>
        <Input
          aria-label={`Step ${index + 1} description`}
          placeholder="What this step does"
          value={step.description}
          onChange={(e) => update({ description: e.target.value })}
          className={cn(fieldClass, "min-w-48 flex-1")}
        />
        <div className="flex items-center">
          <Button variant="ghost" size="icon" className="size-8" aria-label={`Move step ${index + 1} up`} disabled={isFirst} onClick={() => onMove(-1)}>
            <ArrowUp />
          </Button>
          <Button variant="ghost" size="icon" className="size-8" aria-label={`Move step ${index + 1} down`} disabled={isLast} onClick={() => onMove(1)}>
            <ArrowDown />
          </Button>
          <Button variant="ghost" size="icon" className="size-8" aria-label={`Delete step ${index + 1}`} onClick={onRemove}>
            <Trash2 />
          </Button>
        </div>
      </div>

      <div className="mt-2 grid gap-2 pl-0 sm:pl-9 md:grid-cols-2">
        {meta.locator !== "none" ? (
          <fieldset className="flex flex-wrap gap-2 md:col-span-2">
            <legend className="sr-only">Element</legend>
            {meta.locator === "optional" && !step.locator ? (
              <Button variant="ghost" size="sm" onClick={() => updateLocator({})}>
                Target a specific element
              </Button>
            ) : (
              <>
                <NativeSelect
                  aria-label={`Step ${index + 1} locator strategy`}
                  value={step.locator?.strategy ?? "role"}
                  onChange={(e) => updateLocator({ strategy: e.target.value as PlanLocator["strategy"] })}
                  className="w-40"
                >
                  {STRATEGIES.map(([value, label]) => (
                    <option key={value} value={value}>
                      {label}
                    </option>
                  ))}
                </NativeSelect>
                {step.locator?.strategy === "role" ? (
                  <NativeSelect
                    aria-label={`Step ${index + 1} role`}
                    value={step.locator.role ?? "button"}
                    onChange={(e) => updateLocator({ role: e.target.value as PlanLocator["role"] })}
                    className="w-36"
                  >
                    {ROLES.map((role) => (
                      <option key={role} value={role}>
                        {role}
                      </option>
                    ))}
                  </NativeSelect>
                ) : null}
                <Input
                  aria-label={`Step ${index + 1} element`}
                  placeholder={step.locator?.strategy === "role" ? "Accessible name, e.g. Sign in" : "Element text or selector"}
                  value={step.locator?.value ?? ""}
                  onChange={(e) => updateLocator({ value: e.target.value })}
                  className={cn(fieldClass, "min-w-40 flex-1", step.locator?.strategy === "css" && "font-mono")}
                />
                <label className="flex items-center gap-1.5 text-xs text-muted">
                  <input
                    type="checkbox"
                    checked={Boolean(step.locator?.exact)}
                    onChange={(e) => updateLocator({ exact: e.target.checked })}
                    className="accent-[var(--beacon)]"
                  />
                  Exact match
                </label>
                {meta.locator === "optional" ? (
                  <Button variant="ghost" size="sm" onClick={() => update({ locator: null })}>
                    Use the whole page
                  </Button>
                ) : null}
              </>
            )}
          </fieldset>
        ) : null}

        {meta.value ? (
          <Input
            aria-label={`Step ${index + 1} ${meta.value.toLowerCase()}`}
            placeholder={meta.valueHint ? `${meta.value}, e.g. ${meta.valueHint}` : meta.value}
            value={step.value ?? ""}
            onChange={(e) => update({ value: e.target.value })}
            className={cn(fieldClass, "font-mono")}
          />
        ) : null}
        {meta.match ? (
          <NativeSelect
            aria-label={`Step ${index + 1} match`}
            value={step.match ?? "contains"}
            onChange={(e) => update({ match: e.target.value as PlanStep["match"] })}
          >
            <option value="contains">Contains</option>
            <option value="exact">Exactly</option>
          </NativeSelect>
        ) : null}
        {meta.state ? (
          <NativeSelect
            aria-label={`Step ${index + 1} state`}
            value={step.state ?? "visible"}
            onChange={(e) => update({ state: e.target.value as PlanStep["state"] })}
          >
            <option value="visible">Until visible</option>
            <option value="hidden">Until hidden</option>
            <option value="attached">Until attached</option>
            <option value="detached">Until removed</option>
          </NativeSelect>
        ) : null}
      </div>

      {messages.length ? (
        <ul className="mt-2 space-y-1 pl-0 sm:pl-9">
          {messages.map((m) => (
            <li
              key={m.message}
              className={cn("flex items-start gap-1.5 text-xs", m.severity === "error" ? "text-failed" : "text-warning")}
            >
              {m.severity === "error" ? (
                <CircleX className="mt-px size-3.5 shrink-0" aria-hidden />
              ) : (
                <AlertTriangle className="mt-px size-3.5 shrink-0" aria-hidden />
              )}
              {m.message}
            </li>
          ))}
        </ul>
      ) : null}
    </li>
  );
}
