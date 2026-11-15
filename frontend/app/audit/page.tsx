import type { Metadata } from "next";

import { AuditTrail } from "@/features/audit/AuditTrail";

export const metadata: Metadata = { title: "Audit & Reports" };

export default function AuditPage() {
  return <AuditTrail />;
}
