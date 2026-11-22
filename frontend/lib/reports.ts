import { API_ORIGIN, authHeaders } from "@/lib/api";

/** Download an incident's recovery report (Markdown) with the session's token. */
export async function downloadReport(incident: { id: string; reference: string }): Promise<void> {
  const res = await fetch(`${API_ORIGIN}/api/v1/reports/incidents/${incident.id}?format=markdown`, {
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error(`Report download failed (${res.status}).`);
  const url = URL.createObjectURL(await res.blob());
  const a = document.createElement("a");
  a.href = url;
  a.download = `${incident.reference}-report.md`;
  a.click();
  URL.revokeObjectURL(url);
}
