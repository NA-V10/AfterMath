"use client";

import {
  Activity,
  Bot,
  FlaskConical,
  LayoutDashboard,
  Network,
  ScrollText,
  Wrench,
  type LucideIcon,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

import { cn } from "@/components/ui/primitives";
import { useSystemStatus } from "@/lib/queries";

interface NavItem {
  href: string;
  label: string;
  icon: LucideIcon;
}

const NAV: NavItem[] = [
  { href: "/", label: "Command Center", icon: LayoutDashboard },
  { href: "/twin", label: "Infrastructure Twin", icon: Network },
  { href: "/lab", label: "Simulation Lab", icon: FlaskConical },
  { href: "/recovery", label: "Recovery Command", icon: Wrench },
  { href: "/agents", label: "Agent Activity", icon: Bot },
  { href: "/audit", label: "Audit & Reports", icon: ScrollText },
];

export const SIMULATION_NOTICE = "SIMULATION ENVIRONMENT — NOT CONNECTED TO LIVE INFRASTRUCTURE";

function SimulationBanner() {
  return (
    <div
      role="note"
      aria-label="Simulation environment notice"
      data-testid="simulation-banner"
      className="flex min-h-6 shrink-0 items-center justify-center gap-2 border-b border-warn/40 bg-warn/10 px-2 py-0.5 text-center text-[10px] font-semibold tracking-[0.12em] text-warn sm:text-[11px]"
    >
      <span aria-hidden className="size-1.5 rounded-full bg-warn" />
      {SIMULATION_NOTICE}
    </div>
  );
}

function ConnectionStatus() {
  const { data, isError, isPending } = useSystemStatus();
  const state = isPending ? "connecting" : isError ? "offline" : "online";
  const color = { connecting: "bg-inactive", offline: "bg-crit", online: "bg-ok" }[state];
  return (
    <div className="flex items-center gap-3 text-[11px] text-muted">
      {data?.dataset && (
        <span className="hidden font-mono sm:inline" title={data.dataset.content_hash}>
          {data.dataset.name}@{data.dataset.version}
        </span>
      )}
      <span className="flex items-center gap-1.5" aria-live="polite">
        <span aria-hidden className={cn("size-2 rounded-full", color)} />
        API {state}
      </span>
    </div>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  return (
    <div className="flex h-dvh flex-col overflow-hidden">
      <SimulationBanner />
      <header className="flex h-10 shrink-0 items-center justify-between border-b border-line bg-panel px-3">
        <div className="flex items-center gap-2">
          <Activity className="size-4 text-crit" aria-hidden />
          <span className="font-mono text-[13px] font-bold tracking-[0.25em]">AFTERMATH</span>
          <span className="hidden text-[11px] text-dim md:inline">
            Infrastructure resilience &amp; recovery
          </span>
        </div>
        <ConnectionStatus />
      </header>
      <div className="flex min-h-0 flex-1 flex-col md:flex-row">
        <nav
          aria-label="Primary"
          className="flex shrink-0 overflow-x-auto border-b border-line bg-panel md:w-48 md:flex-col md:border-r md:border-b-0"
        >
          {NAV.map(({ href, label, icon: Icon }) => {
            const active = href === "/" ? pathname === "/" : pathname.startsWith(href);
            return (
              <Link
                key={href}
                href={href}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "flex shrink-0 items-center gap-2 border-b-2 border-transparent px-3 py-2 text-[12px] text-muted hover:bg-raised hover:text-fg md:border-b-0 md:border-l-2",
                  active && "border-focus bg-raised text-fg",
                )}
              >
                <Icon className="size-4 shrink-0" aria-hidden />
                <span className="whitespace-nowrap">{label}</span>
              </Link>
            );
          })}
        </nav>
        <main className="min-h-0 min-w-0 flex-1 overflow-auto">{children}</main>
      </div>
    </div>
  );
}
