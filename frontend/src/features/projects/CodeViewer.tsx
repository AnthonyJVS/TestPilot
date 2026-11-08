import { Check, Copy } from "lucide-react";
import { useState } from "react";

import { ErrorState } from "@/components/common/ErrorState";
import { Button } from "@/components/ui/button";
import { NativeSelect } from "@/components/ui/native-select";
import { Skeleton } from "@/components/ui/skeleton";
import { cn, formatDateTime } from "@/lib/utils";

import { useVersion } from "./api";

type Language = "python" | "typescript";

export function CodeViewer({
  versions,
  currentVersionId,
}: {
  versions: { id: string; version: number; created_at: string }[];
  currentVersionId: string | null;
}) {
  const [selected, setSelected] = useState(currentVersionId ?? versions[versions.length - 1]?.id ?? null);
  const [language, setLanguage] = useState<Language>("python");
  const [copied, setCopied] = useState(false);
  const version = useVersion(selected);
  const code = version.data ? (language === "python" ? version.data.code_python : version.data.code_typescript) : "";

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard blocked: the code is still selectable */
    }
  };

  return (
    <section aria-labelledby="code-heading" className="space-y-3">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 id="code-heading" className="text-lg font-semibold">
            Playwright code
          </h2>
          <p className="text-[13px] text-muted">
            Rendered deterministically from the approved plan, without AI. The code you read is exactly what was approved.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <NativeSelect aria-label="Version" value={selected ?? ""} onChange={(e) => setSelected(e.target.value)} className="w-44">
            {[...versions].reverse().map((v) => (
              <option key={v.id} value={v.id}>
                Version {v.version}
                {v.id === currentVersionId ? " (current)" : ""}
              </option>
            ))}
          </NativeSelect>
          <div role="tablist" aria-label="Language" className="flex rounded-control border border-border-strong p-0.5">
            {(["python", "typescript"] as const).map((lang) => (
              <button
                key={lang}
                type="button"
                role="tab"
                aria-selected={language === lang}
                onClick={() => setLanguage(lang)}
                className={cn(
                  "rounded-[3px] px-3 py-1.5 text-[13px]",
                  language === lang ? "bg-raised text-text" : "text-muted hover:text-text",
                )}
              >
                {lang === "python" ? "Python" : "TypeScript"}
              </button>
            ))}
          </div>
          <Button variant="secondary" size="sm" onClick={() => void copy()} disabled={!code}>
            {copied ? <Check /> : <Copy />} {copied ? "Copied" : "Copy"}
          </Button>
        </div>
      </div>
      {version.isPending ? (
        <Skeleton className="h-64 rounded-panel" />
      ) : version.error ? (
        <ErrorState error={version.error} onRetry={() => void version.refetch()} />
      ) : (
        <>
          <pre
            tabIndex={0}
            aria-label={`${language === "python" ? "Python" : "TypeScript"} code for version ${version.data.version}`}
            className="max-h-[480px] overflow-auto rounded-panel border border-border bg-sunken p-4 font-mono text-[12.5px] leading-6 text-text"
          >
            {code}
          </pre>
          <p className="text-xs text-faint">
            Approved {formatDateTime(version.data.created_at)}. Renderer v{version.data.renderer_version}. Test data comes from
            environment variables at run time.
          </p>
        </>
      )}
    </section>
  );
}
