"use client";

import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, unwrap, type Schemas } from "@/lib/api";
import { setSession } from "@/lib/session";

export type AssetCategory = Schemas["AssetSummary"]["category"];
export type PhysicalCondition = Schemas["AssetSummary"]["condition"];
export type Direction = Schemas["TraversalResult"]["direction"];

export interface AssetFilters {
  categories: AssetCategory[];
  conditions: PhysicalCondition[];
  minCriticality: number;
  q: string;
}

export const EMPTY_FILTERS: AssetFilters = { categories: [], conditions: [], minCriticality: 0, q: "" };

const STATIC = { staleTime: 5 * 60_000 } as const;

export function useSystemStatus() {
  return useQuery({
    queryKey: ["system", "status"],
    queryFn: () => unwrap(api.GET("/api/v1/system/status")),
    refetchInterval: 30_000,
    retry: 0,
  });
}

export function useAssets(filters: AssetFilters) {
  return useQuery({
    queryKey: ["infrastructure", "assets", filters],
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/infrastructure/assets", {
          params: {
            query: {
              category: filters.categories.length ? filters.categories : undefined,
              condition: filters.conditions.length ? filters.conditions : undefined,
              min_criticality: filters.minCriticality || undefined,
              q: filters.q.trim() || undefined,
              limit: 200,
            },
          },
        }),
      ),
    placeholderData: keepPreviousData,
    ...STATIC,
  });
}

export function useAsset(code: string | null) {
  return useQuery({
    queryKey: ["infrastructure", "asset", code],
    queryFn: () =>
      unwrap(api.GET("/api/v1/infrastructure/assets/{code}", { params: { path: { code: code! } } })),
    enabled: code !== null,
    ...STATIC,
  });
}

export function useTraversal(code: string | null, direction: Direction) {
  return useQuery({
    queryKey: ["infrastructure", "traversal", code, direction],
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/infrastructure/assets/{code}/dependencies", {
          params: { path: { code: code! }, query: { direction } },
        }),
      ),
    enabled: code !== null,
    ...STATIC,
  });
}

export function useGraph() {
  return useQuery({
    queryKey: ["infrastructure", "graph"],
    queryFn: () => unwrap(api.GET("/api/v1/infrastructure/graph")),
    ...STATIC,
  });
}

export function useBasemap() {
  return useQuery({
    queryKey: ["infrastructure", "basemap"],
    queryFn: () => unwrap(api.GET("/api/v1/infrastructure/basemap")),
    ...STATIC,
  });
}

export function useInfrastructureHealth() {
  return useQuery({
    queryKey: ["infrastructure", "health"],
    queryFn: () => unwrap(api.GET("/api/v1/infrastructure/health")),
    ...STATIC,
  });
}

export function useAuditLog(cursor: string | null) {
  return useQuery({
    queryKey: ["audit", cursor],
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/audit", {
          params: { query: { limit: 50, cursor: cursor ? Number(cursor) : undefined } },
        }),
      ),
    placeholderData: keepPreviousData,
  });
}

// ------------------------------------------------------------------ Phase 2: simulation
export type FunctionalStatus = Schemas["AssetState"]["status"];
export type SimulationRequest = Schemas["SimulationRequest"];

export function useScenarios() {
  return useQuery({
    queryKey: ["scenarios"],
    queryFn: () => unwrap(api.GET("/api/v1/scenarios")),
    ...STATIC,
  });
}

export function useSimulations() {
  return useQuery({
    queryKey: ["simulations", "list"],
    queryFn: () => unwrap(api.GET("/api/v1/simulations", { params: { query: { limit: 50 } } })),
  });
}

export function useSimulation(id: string | null) {
  return useQuery({
    queryKey: ["simulations", "detail", id],
    queryFn: () =>
      unwrap(api.GET("/api/v1/simulations/{simulation_id}", { params: { path: { simulation_id: id! } } })),
    enabled: id !== null,
    staleTime: Infinity, // runs are immutable
  });
}

export function useSimulationEvents(id: string | null) {
  return useQuery({
    queryKey: ["simulations", "events", id],
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/simulations/{simulation_id}/events", {
          params: { path: { simulation_id: id! } },
        }),
      ),
    enabled: id !== null,
    staleTime: Infinity,
  });
}

export function useComparison(a: string | null, b: string | null) {
  return useQuery({
    queryKey: ["simulations", "compare", a, b],
    queryFn: () =>
      unwrap(api.GET("/api/v1/simulations/compare", { params: { query: { ids: `${a},${b}` } } })),
    enabled: a !== null && b !== null,
    staleTime: Infinity,
  });
}

export function useRunSimulation() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: SimulationRequest) => unwrap(api.POST("/api/v1/simulations", { body })),
    onSuccess: (detail) => {
      client.setQueryData(["simulations", "detail", detail.id], detail);
      void client.invalidateQueries({ queryKey: ["simulations", "list"] });
      void client.invalidateQueries({ queryKey: ["picture"] }); // the run may have been applied
    },
  });
}

export function useReplay() {
  return useMutation({
    mutationFn: (id: string) =>
      unwrap(
        api.POST("/api/v1/simulations/{simulation_id}/replay", {
          params: { path: { simulation_id: id } },
        }),
      ),
  });
}

export function usePicture() {
  return useQuery({
    queryKey: ["picture"],
    queryFn: () => unwrap(api.GET("/api/v1/operational-picture")),
  });
}

export function useApplyPicture() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string) =>
      unwrap(
        api.POST("/api/v1/operational-picture/apply/{simulation_id}", {
          params: { path: { simulation_id: id } },
        }),
      ),
    onSuccess: (picture) => client.setQueryData(["picture"], picture),
  });
}

export function useResetPicture() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (reason: string | null) =>
      unwrap(api.POST("/api/v1/operational-picture/reset", { body: { reason } })),
    onSuccess: (picture) => client.setQueryData(["picture"], picture),
  });
}

export function useCriticality() {
  return useQuery({
    queryKey: ["infrastructure", "criticality"],
    queryFn: () => unwrap(api.GET("/api/v1/infrastructure/criticality")),
    ...STATIC,
  });
}

// ------------------------------------------------------------------ Phase 3: agents
export type Workflow = Schemas["WorkflowOut"];
export type AgentExecution = Schemas["ExecutionOut"];
const ACTIVE = new Set(["RUNNING"]);

export function useAgents() {
  return useQuery({
    queryKey: ["agents"],
    queryFn: () => unwrap(api.GET("/api/v1/agents")),
    ...STATIC,
  });
}

export function useIncidents() {
  return useQuery({
    queryKey: ["incidents"],
    queryFn: () => unwrap(api.GET("/api/v1/incidents", { params: { query: { limit: 50 } } })),
  });
}

export function useWorkflows(incidentId: string | null) {
  return useQuery({
    queryKey: ["workflows", "list", incidentId],
    queryFn: () =>
      unwrap(api.GET("/api/v1/workflows", { params: { query: { incident_id: incidentId!, limit: 10 } } })),
    enabled: incidentId !== null,
  });
}

/** Workflow detail; polls while running (SSE pushes updates too, see useWorkflowStream). */
export function useWorkflow(id: string | null) {
  return useQuery({
    queryKey: ["workflows", "detail", id],
    queryFn: () =>
      unwrap(api.GET("/api/v1/workflows/{run_id}", { params: { path: { run_id: id! } } })),
    enabled: id !== null,
    refetchInterval: (q) => (q.state.data && ACTIVE.has(q.state.data.status) ? 2000 : false),
  });
}

export function useCreateIncident() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: Schemas["StructuredIncidentCreate"] | Schemas["FreeTextIncidentCreate"]) =>
      unwrap(api.POST("/api/v1/incidents", { body })),
    onSuccess: () => void client.invalidateQueries({ queryKey: ["incidents"] }),
  });
}

export function useAnalyze() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (incidentId: string) =>
      unwrap(
        api.POST("/api/v1/incidents/{incident_id}/analyze", {
          params: { path: { incident_id: incidentId } },
        }),
      ),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["incidents"] });
      void client.invalidateQueries({ queryKey: ["workflows", "list"] });
    },
  });
}

export function useClarify(runId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: Schemas["ClarificationIn"]) =>
      unwrap(
        api.POST("/api/v1/workflows/{run_id}/clarify", {
          params: { path: { run_id: runId } },
          body,
        }),
      ),
    onSuccess: () => void client.invalidateQueries({ queryKey: ["workflows", "detail", runId] }),
  });
}

// ------------------------------------------------------------------ Phase 4: recovery
export type StrategyDetail = Schemas["StrategyDetail"];
export type StrategyRound = Schemas["StrategyRound"];

export function useInventory() {
  return useQuery({ queryKey: ["inventory"], queryFn: () => unwrap(api.GET("/api/v1/inventory")) });
}

export function useStrategyRound(incidentId: string | null) {
  return useQuery({
    queryKey: ["recovery", "round", incidentId],
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/recovery/strategies/compare", { params: { query: { incident_id: incidentId! } } }),
      ),
    enabled: incidentId !== null,
    retry: false, // 404 simply means "not planned yet"
  });
}

export function useGenerateStrategies() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (incidentId: string) =>
      unwrap(api.POST("/api/v1/recovery/strategies", { body: { incident_id: incidentId } })),
    onSuccess: (round) => {
      client.setQueryData(["recovery", "round", round.incident_id], round);
      void client.invalidateQueries({ queryKey: ["incidents"] });
    },
  });
}

export function useValidateStrategy(incidentId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (strategyId: string) =>
      unwrap(
        api.POST("/api/v1/recovery/strategies/{strategy_id}/validate", {
          params: { path: { strategy_id: strategyId } },
        }),
      ),
    onSettled: () => void client.invalidateQueries({ queryKey: ["recovery", "round", incidentId] }),
  });
}

// ------------------------------------------------------------------ Phase 5: auth & governance
export type Execution = Schemas["RecoveryExecutionOut"];

export async function signIn(username: string, password: string) {
  const out = await unwrap(api.POST("/api/v1/auth/token", { body: { username, password } }));
  setSession({ token: out.access_token, expiresAt: out.expires_at, user: out.user });
  return out;
}

export function useMe(enabled: boolean) {
  return useQuery({
    queryKey: ["auth", "me"],
    queryFn: () => unwrap(api.GET("/api/v1/auth/me")),
    enabled,
    staleTime: 60_000,
  });
}

/** After any governance decision, refresh everything that shows strategy or incident state. */
function useGovernanceRefresh(incidentId: string) {
  const client = useQueryClient();
  return () => {
    void client.invalidateQueries({ queryKey: ["recovery", "round", incidentId] });
    void client.invalidateQueries({ queryKey: ["recovery", "execution"] });
    void client.invalidateQueries({ queryKey: ["incidents"] });
    void client.invalidateQueries({ queryKey: ["inventory"] });
    void client.invalidateQueries({ queryKey: ["picture"] });
    void client.invalidateQueries({ queryKey: ["audit"] });
  };
}

export interface DecisionInput {
  strategyId: string;
  contentHash: string;
  version: number;
  comment: string;
}

export function useDecide(incidentId: string, decision: "approve" | "reject") {
  const refresh = useGovernanceRefresh(incidentId);
  return useMutation({
    mutationFn: ({ strategyId, contentHash, version, comment }: DecisionInput) => {
      const path = { strategy_id: strategyId };
      const base = { content_hash: contentHash, expected_version: version };
      return decision === "approve"
        ? unwrap(
            api.POST("/api/v1/recovery/strategies/{strategy_id}/approve", {
              params: { path },
              body: { ...base, comment: comment.trim() || null },
            }),
          )
        : unwrap(
            api.POST("/api/v1/recovery/strategies/{strategy_id}/reject", {
              params: { path },
              body: { ...base, comment },
            }),
          );
    },
    onSettled: refresh,
  });
}

export function useExecute(incidentId: string) {
  const refresh = useGovernanceRefresh(incidentId);
  return useMutation({
    mutationFn: ({ strategyId, idempotencyKey }: { strategyId: string; idempotencyKey: string }) =>
      unwrap(
        api.POST("/api/v1/recovery/strategies/{strategy_id}/execute", {
          params: { path: { strategy_id: strategyId }, header: { "Idempotency-Key": idempotencyKey } },
        }),
      ),
    onSettled: refresh,
  });
}

export function useExecution(id: string | null | undefined) {
  return useQuery({
    queryKey: ["recovery", "execution", id],
    queryFn: () =>
      unwrap(api.GET("/api/v1/recovery/executions/{execution_id}", { params: { path: { execution_id: id! } } })),
    enabled: !!id,
    staleTime: Infinity, // executions are immutable
  });
}

export function useCloseIncident(incidentId: string) {
  const refresh = useGovernanceRefresh(incidentId);
  return useMutation({
    mutationFn: (reason: string) =>
      unwrap(
        api.POST("/api/v1/incidents/{incident_id}/close", {
          params: { path: { incident_id: incidentId } },
          body: { reason },
        }),
      ),
    onSettled: refresh,
  });
}

export function useVerifyChain() {
  return useMutation({ mutationFn: () => unwrap(api.GET("/api/v1/audit/verify-chain")) });
}
