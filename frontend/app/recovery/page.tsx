import type { Metadata } from "next";

import { PhaseNotice } from "@/components/shell/PhaseNotice";

export const metadata: Metadata = { title: "Recovery Command" };

export default function RecoveryCommandPage() {
  return (
    <PhaseNotice
      title="Recovery Command"
      phase={4}
      summary="Compare three resource-constrained recovery strategies, review the action sequence and resources, and approve or reject a plan."
      needs={[
        "Phase 4 recovery scheduler, resource inventory and validator",
        "Phase 5 approval, execution and verification workflow",
      ]}
    />
  );
}
