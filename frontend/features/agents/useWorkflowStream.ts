"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { API_ORIGIN } from "@/lib/api";
import type { Workflow } from "@/lib/queries";

export type StreamState = "idle" | "live" | "closed" | "unavailable";

/**
 * Subscribes to the workflow's Server-Sent Events stream and writes each snapshot into the
 * query cache. If SSE is unavailable, the detail query's polling keeps the view current.
 */
export function useWorkflowStream(runId: string | null, active: boolean): StreamState {
  const client = useQueryClient();
  const [state, setState] = useState<StreamState>("idle");

  useEffect(() => {
    if (!runId || !active || typeof EventSource === "undefined") return;
    const source = new EventSource(`${API_ORIGIN}/api/v1/workflows/${runId}/events`);
    source.addEventListener("open", () => setState("live"));
    source.addEventListener("workflow", (e) => {
      const snapshot = JSON.parse((e as MessageEvent<string>).data) as Workflow;
      client.setQueryData(["workflows", "detail", runId], snapshot);
      if (snapshot.status !== "RUNNING") {
        source.close();
        setState("closed");
        void client.invalidateQueries({ queryKey: ["incidents"] });
        void client.invalidateQueries({ queryKey: ["picture"] });
        void client.invalidateQueries({ queryKey: ["simulations", "list"] });
      }
    });
    source.addEventListener("error", () => {
      // The server closes the stream after a terminal status; anything else falls back to polling.
      source.close();
      setState((s) => (s === "closed" ? s : "unavailable"));
    });
    return () => source.close();
  }, [runId, active, client]);

  return state;
}
