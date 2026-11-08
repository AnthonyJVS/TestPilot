import type { ReactNode } from "react";

import { Logo } from "@/components/common/Logo";

/**
 * Sign-in and registration frame. A single horizon line levels out behind the form on load —
 * the product's one orchestrated motion (disabled under prefers-reduced-motion).
 */
export function AuthLayout({ title, subtitle, children, footer }: {
  title: string;
  subtitle: string;
  children: ReactNode;
  footer: ReactNode;
}) {
  return (
    <div className="relative grid min-h-dvh place-items-center overflow-hidden px-4 py-12">
      <div aria-hidden className="pointer-events-none absolute inset-0">
        <div className="animate-level-flight absolute inset-x-[-10%] top-1/2">
          <div className="h-px bg-gradient-to-r from-transparent via-beacon/70 to-transparent" />
          <div className="h-[40vh] bg-gradient-to-b from-ground/10 to-transparent" />
        </div>
        <div className="absolute inset-x-0 top-0 h-1/2 bg-gradient-to-b from-sky/[0.07] to-transparent" />
      </div>

      <div className="relative w-full max-w-[400px]">
        <Logo className="mb-10" />
        <h1 className="text-[28px] font-semibold">{title}</h1>
        <p className="mt-2 text-muted">{subtitle}</p>
        <div className="mt-8 rounded-panel border border-border bg-panel/90 p-6 shadow-2xl shadow-black/20 backdrop-blur">
          {children}
        </div>
        <div className="mt-6 text-sm text-muted">{footer}</div>
      </div>
    </div>
  );
}
