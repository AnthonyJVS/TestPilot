import { Link } from "react-router";

import { Button } from "@/components/ui/button";

export function NotFoundPage() {
  return (
    <div className="mx-auto max-w-md py-16">
      <h1 className="text-[26px] font-semibold">Page not found</h1>
      <p className="mt-2 text-muted">This address does not match any section of TestPilot.</p>
      <Button asChild variant="secondary" className="mt-6">
        <Link to="/">Go to dashboard</Link>
      </Button>
    </div>
  );
}
