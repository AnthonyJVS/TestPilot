import { Switch as Primitive } from "radix-ui";
import * as React from "react";

import { cn } from "@/lib/utils";

export function Switch({ className, ...props }: React.ComponentProps<typeof Primitive.Root>) {
  return (
    <Primitive.Root
      className={cn(
        "relative inline-flex h-6 w-10 shrink-0 cursor-pointer items-center rounded-full border border-border-strong",
        "bg-sunken transition-colors data-[state=checked]:border-beacon data-[state=checked]:bg-beacon",
        "disabled:cursor-not-allowed disabled:opacity-50",
        className,
      )}
      {...props}
    >
      <Primitive.Thumb
        className={cn(
          "block size-4 translate-x-1 rounded-full bg-muted transition-transform",
          "data-[state=checked]:translate-x-[19px] data-[state=checked]:bg-beacon-foreground",
        )}
      />
    </Primitive.Root>
  );
}
