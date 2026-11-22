/** Strategy lifecycle display (docs/DATA_MODEL.md §9). Colors reuse the app's status palette. */
export const STRATEGY_STATUS: Record<string, { label: string; color: string }> = {
  DRAFT: { label: "draft", color: "#8b949e" },
  VALIDATED: { label: "valid", color: "#3fb950" },
  VALIDATION_FAILED: { label: "validation failed", color: "#f85149" },
  APPROVED: { label: "approved", color: "#3fb950" },
  REJECTED: { label: "rejected", color: "#f85149" },
  SUPERSEDED: { label: "superseded", color: "#8b949e" },
  EXECUTING: { label: "executing", color: "#d29922" },
  EXECUTED: { label: "executed", color: "#d29922" },
  EXECUTION_FAILED: { label: "execution failed", color: "#f85149" },
  VERIFIED: { label: "executed · verified", color: "#3fb950" },
};

export function strategyStatus(status: string): { label: string; color: string } {
  return STRATEGY_STATUS[status] ?? { label: status.toLowerCase(), color: "#8b949e" };
}
