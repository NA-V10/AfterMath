import type { Metadata } from "next";

import { AgentActivity } from "@/features/agents/AgentActivity";

export const metadata: Metadata = { title: "Agent Activity" };

export default function AgentActivityPage() {
  return <AgentActivity />;
}
