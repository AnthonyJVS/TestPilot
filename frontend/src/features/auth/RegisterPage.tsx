import { zodResolver } from "@hookform/resolvers/zod";
import { useForm, type UseFormSetError } from "react-hook-form";
import { Link } from "react-router";
import { z } from "zod";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ApiError } from "@/lib/api-client";

import { useRegister } from "./api";
import { AuthLayout } from "./AuthLayout";
import { FormAlert, FormField } from "./FormField";

// Mirrors the backend rules in app/schemas/auth.py; the server stays the source of truth.
const schema = z
  .object({
    display_name: z.string().trim().min(1, "Enter your name.").max(100),
    email: z.email("Enter a valid email address."),
    password: z
      .string()
      .min(12, "Use at least 12 characters.")
      .max(128, "Use at most 128 characters.")
      .refine((v) => v.trim() === v, "Remove spaces at the start or end."),
  })
  .refine((v) => v.password.toLowerCase() !== v.email.trim().toLowerCase(), {
    path: ["password"],
    message: "Your password must differ from your email.",
  });

type Values = z.infer<typeof schema>;

const FIELDS: (keyof Values)[] = ["display_name", "email", "password"];

/** Show backend validation messages (e.g. "too repetitive") next to the matching field. */
function applyServerFieldErrors(error: unknown, setError: UseFormSetError<Values>): void {
  if (!(error instanceof ApiError) || !Array.isArray(error.details)) return;
  for (const item of error.details as { loc?: unknown[]; msg?: string }[]) {
    const field = item.loc?.[1];
    if (typeof field === "string" && (FIELDS as string[]).includes(field) && item.msg) {
      const message = item.msg.replace(/^Value error, /, "").replace(/^value is not a valid email address: /, "");
      setError(field as keyof Values, { message });
    }
  }
}

function registerErrorMessage(error: unknown): string | null {
  if (!error) return null;
  if (error instanceof ApiError) {
    if (error.code === "request.validation_failed") return "Check the highlighted fields and try again.";
    return error.message;
  }
  return "Registration failed. Try again.";
}

export function RegisterPage() {
  const registerUser = useRegister();
  const form = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: { display_name: "", email: "", password: "" },
  });

  const onSubmit = form.handleSubmit((values) =>
    registerUser.mutate(values, {
      onError: (error) => applyServerFieldErrors(error, form.setError),
    }),
  );

  return (
    <AuthLayout
      title="Create your account"
      subtitle="Your projects, provider keys and test runs stay private to this account."
      footer={
        <>
          Already have an account?{" "}
          <Link to="/login" className="font-medium text-beacon hover:underline">
            Sign in
          </Link>
        </>
      }
    >
      <form onSubmit={onSubmit} noValidate className="space-y-4">
        <FormAlert message={registerErrorMessage(registerUser.error)} />
        <FormField label="Name" error={form.formState.errors.display_name?.message}>
          {(field) => <Input {...field} autoComplete="name" autoFocus {...form.register("display_name")} />}
        </FormField>
        <FormField label="Email" error={form.formState.errors.email?.message}>
          {(field) => <Input {...field} type="email" autoComplete="email" {...form.register("email")} />}
        </FormField>
        <FormField
          label="Password"
          error={form.formState.errors.password?.message}
          hint="At least 12 characters. A short sentence works well."
        >
          {(field) => (
            <Input {...field} type="password" autoComplete="new-password" {...form.register("password")} />
          )}
        </FormField>
        <Button type="submit" className="w-full" disabled={registerUser.isPending}>
          {registerUser.isPending ? "Creating account…" : "Create account"}
        </Button>
      </form>
    </AuthLayout>
  );
}
