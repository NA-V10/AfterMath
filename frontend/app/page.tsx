import type { Metadata } from "next";

import { CommandCenterOverview } from "@/features/command-center/CommandCenterOverview";

export const metadata: Metadata = { title: "Command Center" };

export default function CommandCenterPage() {
  return <CommandCenterOverview />;
}
