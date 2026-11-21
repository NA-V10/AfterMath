"use client";

import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, unwrap, type Schemas } from "@/lib/api";

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
