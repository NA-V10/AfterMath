import { clsx, type ClassValue } from "clsx";
import { AlertTriangle, Loader2 } from "lucide-react";
import type { ButtonHTMLAttributes, ReactNode } from "react";
import { twMerge } from "tailwind-merge";

import { ApiError } from "@/lib/api";

export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}

/** A titled region of a screen. Titles are sentence case, 15px at 500 (the system's one label look). */
export function Panel({
  title,
  actions,
  children,
  className,
  bodyClassName,
}: {
  title?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClassName?: string;
}) {
  return (
    <section className={cn("flex min-h-0 flex-col border border-line bg-panel", className)}>
      {(title || actions) && (
        <header className="flex min-h-11 shrink-0 items-center justify-between gap-2 border-b border-line px-4">
          <h2 className="truncate text-[15px] font-medium">{title}</h2>
          <div className="flex items-center gap-1.5">{actions}</div>
        </header>
      )}
      <div className={cn("min-h-0 flex-1", bodyClassName)}>{children}</div>
    </section>
  );
}

/** The title row of a screen. It enters once on load (the console's one entrance). */
export function PageHeader({ title, hint, children }: { title: string; hint?: ReactNode; children?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-x-6 gap-y-2 border-b border-line px-5 pt-4 pb-3">
      <div className="page-enter min-w-0">
        <h1 className="text-[24px] leading-tight">{title}</h1>
        {hint && <p className="mt-0.5 text-[13px] text-muted">{hint}</p>}
      </div>
      {children && <div className="flex flex-wrap items-center gap-2">{children}</div>}
    </div>
  );
}

export function SectionLabel({ children }: { children: ReactNode }) {
  return <div className="mb-1.5 text-[13px] font-medium text-muted">{children}</div>;
}

export function Dot({ color, className }: { color: string; className?: string }) {
  return (
    <span
      aria-hidden
      className={cn("inline-block size-2 shrink-0 rounded-full", className)}
      style={{ background: color }}
    />
  );
}

export function Badge({
  children,
  color,
  className,
}: {
  children: ReactNode;
  color?: string;
  className?: string;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-sm border px-1.5 text-[13px] leading-[22px] font-medium",
        className,
      )}
      style={
        color
          ? { color, borderColor: `${color}55`, background: `${color}14` }
          : { borderColor: "var(--color-line-strong)", color: "var(--color-muted)" }
      }
    >
      {children}
    </span>
  );
}

export function Segmented<T extends string>({
  value,
  options,
  onChange,
  label,
}: {
  value: T;
  options: { value: T; label: string }[];
  onChange: (value: T) => void;
  label: string;
}) {
  return (
    <div role="radiogroup" aria-label={label} className="flex rounded-md border border-line-strong p-0.5">
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          role="radio"
          aria-checked={value === o.value}
          onClick={() => onChange(o.value)}
          className={cn(
            "rounded-sm px-2.5 py-1 text-[13px] text-muted transition-colors duration-150 hover:text-fg",
            value === o.value && "bg-fg text-bg hover:text-bg",
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function IconButton({
  className,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { "aria-label": string }) {
  return (
    <button
      type="button"
      className={cn(
        "inline-flex size-8 items-center justify-center rounded-md text-muted transition-colors duration-150 hover:bg-raised hover:text-fg",
        className,
      )}
      {...props}
    />
  );
}

export function Loading({ label = "Loading" }: { label?: string }) {
  return (
    <div role="status" className="flex h-full min-h-16 items-center justify-center gap-2 text-muted">
      <Loader2 className="size-4 animate-spin" aria-hidden />
      <span>{label}…</span>
    </div>
  );
}

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const apiError = error instanceof ApiError ? error : null;
  const title = apiError?.isUnreachable
    ? "Backend unreachable"
    : (apiError?.problem?.title ?? "Something went wrong");
  const detail =
    apiError?.message ?? (error instanceof Error ? error.message : "An unexpected error occurred.");
  return (
    <div role="alert" className="flex h-full min-h-24 flex-col items-center justify-center gap-2 p-4 text-center">
      <AlertTriangle className="size-5 text-warn" aria-hidden />
      <div className="font-medium">{title}</div>
      <div className="max-w-sm text-muted">{detail}</div>
      {apiError?.requestId && (
        <div className="font-mono text-[13px] text-dim">request {apiError.requestId}</div>
      )}
      {onRetry && (
        <button type="button" onClick={onRetry} className="btn btn-secondary btn-sm mt-1">
          Retry
        </button>
      )}
    </div>
  );
}

export function Stat({ label, value, hint }: { label: string; value: ReactNode; hint?: string }) {
  return (
    <div className="min-w-0">
      <div className="truncate text-[13px] text-muted">{label}</div>
      <div className="truncate font-mono text-[16px] tabular-nums" title={hint}>
        {value}
      </div>
    </div>
  );
}
