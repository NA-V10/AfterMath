import type { Metadata } from "next";

import { TwinWorkspace } from "@/features/twin/TwinWorkspace";

export const metadata: Metadata = { title: "Infrastructure Twin" };

export default function TwinPage() {
  return <TwinWorkspace />;
}
