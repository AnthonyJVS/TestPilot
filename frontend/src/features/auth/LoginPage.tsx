import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import { Link, useLocation } from "react-router";
import { z } from "zod";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ApiError } from "@/lib/api-client";

import { useLogin } from "./api";
import { AuthLayout } from "./AuthLayout";
import { FormAlert, FormField } from "./FormField";

const schema = z.object({
  email: z.email("Enter a valid email address."),
  password: z.string().min(1, "Enter your password."),
});

type Values = z.infer<typeof schema>;

function loginErrorMessage(error: unknown): string | null {
  if (!error) return null;
  if (error instanceof ApiError) {
    if (error.code === "rate_limited") {
      const minutes = Math.max(1, Math.ceil((error.retryAfterSeconds ?? 60) / 60));
      return `Too many failed attempts. Try again in ${minutes} minute${minutes === 1 ? "" : "s"}.`;
    }
    return error.message;
  }
  return "Sign-in failed. Try again.";
}

export function LoginPage() {
  const location = useLocation();
  const login = useLogin();
  const form = useForm<Values>({ resolver: zodResolver(schema), defaultValues: { email: "", password: "" } });

  // On success the session store flips to "authenticated" and GuestOnly redirects to `from`.
  const onSubmit = form.handleSubmit((values) => login.mutate(values));

  return (
    <AuthLayout
      title="Sign in"
      subtitle="Plan, run and inspect AI-assisted browser tests."
      footer={
        <>
          New to TestPilot?{" "}
          <Link to="/register" state={location.state} className="font-medium text-beacon hover:underline">
            Create an account
          </Link>
        </>
      }
    >
      <form onSubmit={onSubmit} noValidate className="space-y-4">
        <FormAlert message={loginErrorMessage(login.error)} />
        <FormField label="Email" error={form.formState.errors.email?.message}>
          {(field) => (
            <Input {...field} type="email" autoComplete="email" autoFocus {...form.register("email")} />
          )}
        </FormField>
        <FormField label="Password" error={form.formState.errors.password?.message}>
          {(field) => (
            <Input {...field} type="password" autoComplete="current-password" {...form.register("password")} />
          )}
        </FormField>
        <Button type="submit" className="w-full" disabled={login.isPending}>
          {login.isPending ? "Signing in…" : "Sign in"}
        </Button>
      </form>
    </AuthLayout>
  );
}
