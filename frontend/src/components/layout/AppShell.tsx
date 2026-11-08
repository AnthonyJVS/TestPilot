import { Menu, X } from "lucide-react";
import { Dialog } from "radix-ui";
import { useState } from "react";
import { Outlet } from "react-router";

import { Logo } from "@/components/common/Logo";
import { Button } from "@/components/ui/button";

import { Sidebar, SidebarNav } from "./Sidebar";
import { UserMenu } from "./UserMenu";

export function AppShell() {
  const [mobileOpen, setMobileOpen] = useState(false);

  return (
    <div className="flex min-h-dvh">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-50 focus:rounded-control focus:bg-panel focus:px-3 focus:py-2"
      >
        Skip to content
      </a>
      <Sidebar />

      <Dialog.Root open={mobileOpen} onOpenChange={setMobileOpen}>
        <Dialog.Portal>
          <Dialog.Overlay className="fixed inset-0 z-40 bg-black/50 lg:hidden" />
          <Dialog.Content className="fixed inset-y-0 left-0 z-50 flex w-72 flex-col border-r border-border bg-panel lg:hidden">
            <Dialog.Title className="sr-only">Navigation</Dialog.Title>
            <Dialog.Description className="sr-only">Main application sections</Dialog.Description>
            <div className="flex h-16 items-center justify-between px-5">
              <Logo />
              <Dialog.Close asChild>
                <Button variant="ghost" size="icon" aria-label="Close navigation">
                  <X />
                </Button>
              </Dialog.Close>
            </div>
            <SidebarNav onNavigate={() => setMobileOpen(false)} />
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 flex h-16 items-center gap-3 border-b border-border bg-background/85 px-4 backdrop-blur sm:px-6">
          <Button
            variant="ghost"
            size="icon"
            className="lg:hidden"
            aria-label="Open navigation"
            onClick={() => setMobileOpen(true)}
          >
            <Menu />
          </Button>
          <span className="lg:hidden">
            <Logo />
          </span>
          <div className="ml-auto">
            <UserMenu />
          </div>
        </header>
        <main id="main" className="flex-1 px-4 py-8 sm:px-8">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
