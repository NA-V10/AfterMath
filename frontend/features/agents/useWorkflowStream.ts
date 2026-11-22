"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { API_ORIGIN, authHeaders } from "@/lib/api";
import type { Workflow } from "@/lib/queries";

export type StreamState = "idle" | "live" | "closed" | "unavailable";

/** Split a Server-Sent Events byte stream into `{event, data}` messages. */
export async function* readEvents(
  body: ReadableStream<Uint8Array>,
): AsyncGenerator<{ event: string; data: string }> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) return;
    buffer += decoder.decode(value, { stream: true }).replaceAll("\r\n", "\n");
    let cut: number;
    while ((cut = buffer.indexOf("\n\n")) >= 0) {
      const block = buffer.slice(0, cut);
      buffer = buffer.slice(cut + 2);
      let event = "message";
      const data: string[] = [];
      for (const line of block.split("\n")) {
        if (line.startsWith(":")) continue; // comment / heartbeat
        if (line.startsWith("event:")) event = line.slice(6).trim();
        else if (line.startsWith("data:")) data.push(line.slice(5).trimStart());
      }
      if (data.length) yield { event, data: data.join("\n") };
    }
  }
}

/**
 * Subscribes to the workflow's Server-Sent Events stream and writes each snapshot into the
 * query cache. Uses fetch (not EventSource) so the request can carry the bearer token. If the
 * stream is unavailable, the detail query's polling keeps the view current.
 */
export function useWorkflowStream(runId: string | null, active: boolean): StreamState {
  const client = useQueryClient();
  const [state, setState] = useState<StreamState>("idle");

  useEffect(() => {
    if (!runId || !active) return;
    const abort = new AbortController();
    (async () => {
      try {
        const res = await fetch(`${API_ORIGIN}/api/v1/workflows/${runId}/events`, {
          headers: { Accept: "text/event-stream", ...authHeaders() },
          signal: abort.signal,
        });
        if (!res.ok || !res.body) throw new Error(`stream ${res.status}`);
        setState("live");
        for await (const msg of readEvents(res.body)) {
          if (msg.event !== "workflow") continue;
          const snapshot = JSON.parse(msg.data) as Workflow;
          client.setQueryData(["workflows", "detail", runId], snapshot);
          if (snapshot.status !== "RUNNING") {
            setState("closed");
            void client.invalidateQueries({ queryKey: ["incidents"] });
            void client.invalidateQueries({ queryKey: ["picture"] });
            void client.invalidateQueries({ queryKey: ["simulations", "list"] });
            abort.abort();
            return;
          }
        }
        setState((s) => (s === "closed" ? s : "unavailable"));
      } catch {
        if (!abort.signal.aborted) setState("unavailable"); // polling takes over
      }
    })();
    return () => abort.abort();
  }, [runId, active, client]);

  return state;
}
