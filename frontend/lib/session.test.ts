import { describe, expect, it } from "vitest";

import { readEvents } from "@/features/agents/useWorkflowStream";

import { hasRole, type Session } from "./session";

const as = (role: string): Session => ({
  token: "t",
  expiresAt: new Date(Date.now() + 60_000).toISOString(),
  user: { username: role, display_name: role, roles: [role], role },
});

describe("hasRole", () => {
  it("treats roles as cumulative, like the server", () => {
    expect(hasRole(as("admin"), "approver")).toBe(true);
    expect(hasRole(as("approver"), "operator")).toBe(true);
    expect(hasRole(as("operator"), "approver")).toBe(false);
    expect(hasRole(as("viewer"), "operator")).toBe(false);
    expect(hasRole(null, "viewer")).toBe(true);
    expect(hasRole(null, "operator")).toBe(false);
  });
});

function streamOf(chunks: string[]): ReadableStream<Uint8Array> {
  const enc = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      for (const c of chunks) controller.enqueue(enc.encode(c));
      controller.close();
    },
  });
}

describe("readEvents (SSE over fetch)", () => {
  it("parses events split across chunks and skips heartbeats", async () => {
    const out = [];
    for await (const e of readEvents(
      streamOf(['event: workflow\ndata: {"a"', ':1}\n\n: heartbeat\n\n', "event: workflow\r\ndata: 2\r\n\r\n"]),
    )) {
      out.push(e);
    }
    expect(out).toEqual([
      { event: "workflow", data: '{"a":1}' },
      { event: "workflow", data: "2" },
    ]);
  });
});
