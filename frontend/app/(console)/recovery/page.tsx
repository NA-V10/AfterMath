import type { Metadata } from "next";

import { RecoveryCommand } from "@/features/recovery/RecoveryCommand";

export const metadata: Metadata = { title: "Recovery Command" };

export default function RecoveryCommandPage() {
  return <RecoveryCommand />;
}
