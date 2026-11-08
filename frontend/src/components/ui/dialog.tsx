import { X } from "lucide-react";
import { Dialog as Primitive } from "radix-ui";
import * as React from "react";

import { cn } from "@/lib/utils";

export const Dialog = Primitive.Root;
export const DialogTrigger = Primitive.Trigger;
export const DialogClose = Primitive.Close;

export function DialogContent({
  className,
  children,
  title,
  description,
  ...props
}: React.ComponentProps<typeof Primitive.Content> & { title: string; description?: React.ReactNode }) {
  return (
    <Primitive.Portal>
      <Primitive.Overlay className="fixed inset-0 z-50 bg-black/55 backdrop-blur-[2px]" />
      <Primitive.Content
        className={cn(
          "fixed left-1/2 top-1/2 z-50 max-h-[90dvh] w-[calc(100vw-2rem)] max-w-lg -translate-x-1/2 -translate-y-1/2",
          "overflow-y-auto rounded-panel border border-border-strong bg-panel p-6 shadow-2xl shadow-black/40",
          className,
        )}
        {...props}
      >
        <div className="mb-5 pr-8">
          <Primitive.Title className="text-lg font-semibold [font-stretch:112%]">{title}</Primitive.Title>
          {description ? (
            <Primitive.Description className="mt-1 text-sm text-muted">{description}</Primitive.Description>
          ) : (
            <Primitive.Description className="sr-only">{title}</Primitive.Description>
          )}
        </div>
        {children}
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
