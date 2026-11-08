import { X } from "lucide-react";
import { Dialog as Primitive } from "radix-ui";
import * as React from "react";

import { cn } from "@/lib/utils";

export const Dialog = Primitive.Root;
export const DialogTrigger = Primitive.Trigger;
export const DialogClose = Primitive.Close;

/**
 * Header and footer stay pinned; only the body scrolls. Primary actions therefore remain visible
 * even in short viewports (a side panel, a phone in landscape).
 */
export function DialogContent({
  className,
  children,
  title,
  description,
  footer,
  ...props
}: React.ComponentProps<typeof Primitive.Content> & {
  title: string;
  description?: React.ReactNode;
  footer?: React.ReactNode;
}) {
  return (
    <Primitive.Portal>
      <Primitive.Overlay className="fixed inset-0 z-50 bg-black/55 backdrop-blur-[2px]" />
      <Primitive.Content
        className={cn(
          "fixed left-1/2 top-1/2 z-50 flex max-h-[calc(100dvh-1rem)] w-[calc(100vw-1rem)] max-w-lg -translate-x-1/2 -translate-y-1/2",
          "flex-col rounded-panel border border-border-strong bg-panel shadow-2xl shadow-black/40 sm:max-h-[90dvh] sm:w-[calc(100vw-2rem)]",
          className,
        )}
        {...props}
      >
        <div className="shrink-0 px-5 pt-5 pb-3 pr-12 sm:px-6 sm:pt-6">
          <Primitive.Title className="text-lg font-semibold [font-stretch:112%]">{title}</Primitive.Title>
          {description ? (
            <Primitive.Description className="mt-1 text-sm text-muted">{description}</Primitive.Description>
          ) : (
            <Primitive.Description className="sr-only">{title}</Primitive.Description>
          )}
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto px-5 pb-4 sm:px-6">{children}</div>
        {footer ? (
          <div className="flex shrink-0 justify-end gap-2 border-t border-border px-5 py-3 sm:px-6">{footer}</div>
        ) : null}
        <Primitive.Close
          className="absolute right-4 top-4 rounded-control p-1.5 text-muted hover:bg-raised hover:text-text"
          aria-label="Close"
        >
          <X className="size-4" />
        </Primitive.Close>
      </Primitive.Content>
    </Primitive.Portal>
  );
}
