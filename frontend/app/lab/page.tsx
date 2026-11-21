import type { Metadata } from "next";

import { SimulationLab } from "@/features/simulation/SimulationLab";

export const metadata: Metadata = { title: "Simulation Lab" };

export default function SimulationLabPage() {
  return <SimulationLab />;
}
