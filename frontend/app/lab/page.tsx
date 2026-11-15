import type { Metadata } from "next";

import { PhaseNotice } from "@/components/shell/PhaseNotice";

export const metadata: Metadata = { title: "Simulation Lab" };

export default function SimulationLabPage() {
  return (
    <PhaseNotice
      title="Simulation Lab"
      phase={2}
      summary="Run deterministic cascading-failure simulations on the synthetic district, watch failures propagate wave by wave, inspect the event timeline and compare scenarios."
      needs={[
        "Phase 2 simulation engine (fixed-point propagation + discrete-event timeline)",
        "Simulation persistence and /api/v1/simulations endpoints",
        "Predefined scenarios endpoint (/api/v1/scenarios)",
      ]}
    />
  );
}
