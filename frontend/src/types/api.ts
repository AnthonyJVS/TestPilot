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

export type ProjectSummary = Schemas["ProjectSummaryOut"];
export type Project = Schemas["ProjectOut"];
export type ProjectCreate = Schemas["ProjectCreate"];
export type ProjectUpdate = Schemas["ProjectUpdate"];
export type Environment = Schemas["EnvironmentOut"];
export type Variable = Schemas["VariableOut"];
export type Suite = Schemas["SuiteOut"];
export type CaseSummary = Schemas["CaseSummaryOut"];
export type TestCase = Schemas["CaseOut"];
export type PlanRecord = Schemas["PlanOut"];
export type PlanIssue = Schemas["PlanIssueOut"];
export type TestPlan = Schemas["TestPlan"];
export type TestDataRef = Schemas["TestDataRef"];
export type PlanStep = Schemas["Step"];
export type PlanLocator = Schemas["Locator"];
export type TestVersion = Schemas["VersionOut"];

export type RunCreate = Schemas["RunCreate"];
export type Execution = Schemas["ExecutionOut"];
export type ExecutionSummary = Schemas["ExecutionSummaryOut"];
export type ExecutionStatus = Schemas["ExecutionOut"]["status"];
export type ExecutionStep = Schemas["ExecutionStepOut"];
export type ExecutionEvent = Schemas["ExecutionEventOut"];
export type Artifact = Schemas["ArtifactOut"];
export type ExecutionRuntime = Schemas["ExecutionRuntimeOut"];
export type BrowserName = Schemas["RunCreate"]["browser"];

/** The error envelope every backend failure uses. */
export interface ApiErrorBody {
  error: {
    code: string;
    message: string;
    request_id: string | null;
    details: unknown;
  };
}
