import { Construction } from "lucide-react";

/** Shown on screens whose backend capability is not built yet. Never shows fake data. */
export function PhaseNotice({
  title,
  phase,
  summary,
  needs,
}: {
  title: string;
  phase: number;
  summary: string;
  needs: string[];
}) {
  return (
    <div className="mx-auto flex max-w-2xl flex-col gap-4 p-6">
      <div className="flex items-center gap-2">
        <Construction className="size-5 text-dim" aria-hidden />
        <h1 className="text-lg font-medium">{title}</h1>
        <span className="rounded-sm border border-line-strong px-1.5 text-[13px] text-muted">
          Phase {phase}
        </span>
      </div>
      <p className="text-muted">{summary}</p>
      <div className="border border-line bg-panel p-3">
        <div className="mb-2 text-[13px] font-medium text-dim">
          Not yet available — requires
        </div>
        <ul className="list-disc space-y-1 pl-5 text-muted">
          {needs.map((n) => (
            <li key={n}>{n}</li>
          ))}
        </ul>
      </div>
      <p className="text-[14px] text-dim">
        This screen intentionally shows no placeholder data. It will be connected to real backend
        functionality when the phase above is delivered.
      </p>
    </div>
  );
}
