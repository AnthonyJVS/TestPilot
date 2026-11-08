/**
 * Friendly aliases over the generated OpenAPI types (src/types/openapi.ts).
 * Regenerate with `npm run gen:api` after backend schema changes.
 */
import type { components } from "./openapi";

type Schemas = components["schemas"];

export type User = Schemas["UserOut"];
export type TokenResponse = Schemas["TokenResponse"];
export type LoginRequest = Schemas["LoginRequest"];
export type RegisterRequest = Schemas["RegisterRequest"];
export type SystemStatus = Schemas["SystemStatus"];
export type DependencyStatus = Schemas["DependencyStatus"];
export type DatabaseStatus = Schemas["DatabaseStatus"];
export type AuditLogEntry = Schemas["AuditLogOut"];
export type AuditLogPage = Schemas["AuditLogPage"];

/** The error envelope every backend failure uses. */
export interface ApiErrorBody {
  error: {
    code: string;
    message: string;
    request_id: string | null;
    details: unknown;
  };
}
