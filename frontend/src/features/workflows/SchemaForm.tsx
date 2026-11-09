/**
 * Inspector form generated from a node type's JSON Schema (Pydantic). Supports the shapes the
 * backend uses: strings (input/textarea), enums, booleans, numbers, nullable fields, locator
 * objects, JSON objects and test selection.
 */
import { useState } from "react";

import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { NativeSelect } from "@/components/ui/native-select";
import { Switch } from "@/components/ui/switch";
import { useSuites } from "@/features/projects/api";
import { ROLES, STRATEGIES } from "@/features/projects/plan-actions";

export interface JsonSchema {
  type?: string | string[];
  title?: string;
  description?: string;
  enum?: unknown[];
  default?: unknown;
  properties?: Record<string, JsonSchema>;
  anyOf?: JsonSchema[];
  $ref?: string;
  $defs?: Record<string, JsonSchema>;
  minimum?: number;
  maximum?: number;
  ui?: string;
}

function resolve(schema: JsonSchema, root: JsonSchema): JsonSchema {
  if (schema.$ref?.startsWith("#/$defs/")) {
    const target = root.$defs?.[schema.$ref.slice(8)];
    return target ? { ...target, description: schema.description ?? target.description } : schema;
  }
  return schema;
}

/** Unwrap Optional[X] (anyOf with null). */
function unwrap(schema: JsonSchema, root: JsonSchema): { schema: JsonSchema; nullable: boolean } {
  if (schema.anyOf) {
    const options = schema.anyOf.filter((s) => s.type !== "null");
    const inner = options[0] ? resolve(options[0], root) : {};
    return { schema: { ...inner, description: schema.description ?? inner.description, ui: schema.ui ?? inner.ui }, nullable: true };
  }
  return { schema: resolve(schema, root), nullable: false };
}

const humanize = (key: string) => key.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());

export function SchemaForm({
  schema,
  value,
  onChange,
  projectId,
  idPrefix,
}: {
  schema: JsonSchema;
  value: Record<string, unknown>;
  onChange: (next: Record<string, unknown>) => void;
  projectId: string;
  idPrefix: string;
}) {
  const properties = Object.entries(schema.properties ?? {});
  if (properties.length === 0) return <p className="text-[13px] text-faint">This node has no settings.</p>;
  return (
    <div className="space-y-4">
      {properties.map(([key, raw]) => {
        const { schema: field, nullable } = unwrap(raw, schema);
        const id = `${idPrefix}-${key}`;
        const current = value[key] === undefined ? field.default ?? raw.default : value[key];
        const set = (next: unknown) => onChange({ ...value, [key]: next });
        return (
          <div key={key} className="space-y-1.5">
            <Label htmlFor={id}>{field.title && !field.properties ? field.title : humanize(key)}</Label>
            <Field id={id} field={field} nullable={nullable} value={current} onChange={set} projectId={projectId} />
            {field.description ? <p className="text-xs text-faint">{field.description}</p> : null}
          </div>
        );
      })}
    </div>
  );
}

function Field({
  id,
  field,
  nullable,
  value,
  onChange,
  projectId,
}: {
  id: string;
  field: JsonSchema;
  nullable: boolean;
  value: unknown;
  onChange: (next: unknown) => void;
  projectId: string;
}) {
  if (field.ui === "test_case") return <TestCaseField id={id} value={value as string | null} onChange={onChange} projectId={projectId} />;
  if (field.ui === "json") return <JsonField id={id} value={value} onChange={onChange} />;
  if (field.properties?.strategy) {
    return <LocatorField id={id} value={value as Locator | null} nullable={nullable} onChange={onChange} />;
  }
  if (field.enum) {
    return (
      <NativeSelect id={id} value={String(value ?? "")} onChange={(e) => onChange(e.target.value || (nullable ? null : ""))}>
        {nullable ? <option value="">—</option> : null}
        {field.enum.map((option) => (
          <option key={String(option)} value={String(option)}>
            {humanize(String(option))}
          </option>
        ))}
      </NativeSelect>
    );
  }
  if (field.type === "boolean") return <Switch id={id} checked={Boolean(value)} onCheckedChange={onChange} />;
  if (field.type === "integer" || field.type === "number") {
    return (
      <Input
        id={id}
        type="number"
        min={field.minimum}
        max={field.maximum}
        step={field.type === "integer" ? 1 : "any"}
        value={value === null || value === undefined ? "" : String(value)}
        placeholder={nullable ? "Default" : undefined}
        onChange={(e) => {
          if (e.target.value === "") onChange(nullable ? null : 0);
          else onChange(field.type === "integer" ? Math.round(Number(e.target.value)) : Number(e.target.value));
        }}
      />
    );
  }
  if (field.ui === "textarea") {
    return (
      <textarea
        id={id}
        rows={5}
        value={String(value ?? "")}
        onChange={(e) => onChange(e.target.value)}
        className="w-full rounded-control border border-border-strong bg-sunken px-3 py-2 text-sm focus-visible:border-beacon focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-beacon-soft"
      />
    );
  }
  return <Input id={id} value={String(value ?? "")} onChange={(e) => onChange(e.target.value)} />;
}

interface Locator {
  strategy: string;
  value: string;
  role?: string | null;
  exact?: boolean;
  nth?: number | null;
}

function LocatorField({ id, value, nullable, onChange }: { id: string; value: Locator | null; nullable: boolean; onChange: (next: Locator | null) => void }) {
  if (!value) {
    return (
      <button type="button" id={id} className="text-[13px] text-beacon hover:underline" onClick={() => onChange({ strategy: "label", value: "" })}>
        Add a target element
      </button>
    );
  }
  const update = (patch: Partial<Locator>) => {
    const next = { ...value, ...patch };
    if (next.strategy !== "role") next.role = null;
    else if (!next.role) next.role = "button";
    onChange(next);
  };
  return (
    <div className="space-y-2 rounded-control border border-border bg-sunken/50 p-2.5">
      <div className="grid grid-cols-2 gap-2">
        <NativeSelect id={id} aria-label="Find by" value={value.strategy} onChange={(e) => update({ strategy: e.target.value })}>
          {STRATEGIES.map(([key, label]) => (
            <option key={key} value={key}>
              {label}
            </option>
          ))}
        </NativeSelect>
        {value.strategy === "role" ? (
          <NativeSelect aria-label="Role" value={value.role ?? "button"} onChange={(e) => update({ role: e.target.value })}>
            {ROLES.map((role) => (
              <option key={role} value={role}>
                {role}
              </option>
            ))}
          </NativeSelect>
        ) : (
          <span />
        )}
      </div>
      <Input aria-label="Locator value" placeholder={value.strategy === "role" ? "Accessible name" : "Value"} value={value.value} onChange={(e) => update({ value: e.target.value })} />
      <div className="flex items-center justify-between text-xs text-muted">
        <label className="flex items-center gap-2">
          <Switch checked={Boolean(value.exact)} onCheckedChange={(exact) => update({ exact })} aria-label="Exact match" /> Exact match
        </label>
        {nullable ? (
          <button type="button" className="text-faint hover:text-text" onClick={() => onChange(null)}>
            Remove
          </button>
        ) : null}
      </div>
    </div>
  );
}

function JsonField({ id, value, onChange }: { id: string; value: unknown; onChange: (next: unknown) => void }) {
  const [text, setText] = useState(() => JSON.stringify(value ?? {}, null, 2));
  const [error, setError] = useState<string | null>(null);
  return (
    <>
      <textarea
        id={id}
        rows={5}
        value={text}
        spellCheck={false}
        onChange={(e) => setText(e.target.value)}
        onBlur={() => {
          try {
            const parsed: unknown = JSON.parse(text || "{}");
            if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) throw new Error("Use a JSON object.");
            setError(null);
            onChange(parsed);
          } catch (e) {
            setError(e instanceof Error ? e.message : "Invalid JSON");
          }
        }}
        className="w-full rounded-control border border-border-strong bg-sunken px-3 py-2 font-mono text-xs focus-visible:border-beacon focus-visible:outline-none"
      />
      {error ? <p className="text-xs text-failed">{error}</p> : null}
    </>
  );
}

function TestCaseField({ id, value, onChange, projectId }: { id: string; value: string | null; onChange: (next: string | null) => void; projectId: string }) {
  const suites = useSuites(projectId);
  const cases = (suites.data ?? []).flatMap((s) => s.cases);
  return (
    <NativeSelect id={id} value={value ?? ""} onChange={(e) => onChange(e.target.value || null)}>
      <option value="">Choose a test…</option>
      {cases.map((c) => (
        <option key={c.id} value={c.id} disabled={c.status !== "approved"}>
          {c.name}
          {c.status !== "approved" ? " (not approved)" : ""}
        </option>
      ))}
    </NativeSelect>
  );
}
