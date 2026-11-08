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

export type ProviderType = Schemas["ProviderTypeOut"];
export type Provider = Schemas["ProviderOut"];
export type ProviderCreate = Schemas["ProviderCreate"];
export type AIModel = Schemas["ModelOut"];
export type Capability = Schemas["CapabilityOut"];
export type ConnectionTest = Schemas["ConnectionTestOut"];
export type Routing = Schemas["RoutingOut"];
export type RoutingUpdate = Schemas["RoutingUpdate"];
export type EffectiveRoute = Schemas["EffectiveRouteOut"];
export type TaskCategory = Schemas["EffectiveRouteOut"]["task"];
export type TaskCheck = Schemas["TaskCheckOut"];
export type AIRequestEntry = Schemas["AIRequestOut"];
export type AIRequestPage = Schemas["AIRequestPage"];

/** The error envelope every backend failure uses. */
export interface ApiErrorBody {
  error: {
    code: string;
    message: string;
    request_id: string | null;
    details: unknown;
  };
}
