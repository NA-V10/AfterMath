import type { Metadata } from "next";

import { PhaseNotice } from "@/components/shell/PhaseNotice";

export const metadata: Metadata = { title: "Agent Activity" };

export default function AgentActivityPage() {
  return (
    <PhaseNotice
      title="Agent Activity"
      phase={3}
      summary="Follow SENTINEL, CARTOGRAPHER, ORACLE, STRATEGIST and GUARDIAN through an incident analysis: status, inputs, structured outputs, evidence, retries and errors."
      needs={[
        "Phase 3 LangGraph workflow and agent execution logging",
        "Workflow progress stream (SSE)",
      ]}
    />
  );
}
