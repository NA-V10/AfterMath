"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";

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
