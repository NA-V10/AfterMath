"use client";

import { useQueryClient } from "@tanstack/react-query";
import {
  Bot,
  FlaskConical,
  LayoutDashboard,
  LogOut,
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
import { clearSession, useSession, type Session } from "@/lib/session";

import { SignIn } from "./SignIn";

interface NavItem {
  href: string;
  label: string;
  icon: LucideIcon;
}

const NAV: NavItem[] = [
  { href: "/command", label: "Command Center", icon: LayoutDashboard },
  { href: "/twin", label: "Infrastructure Twin", icon: Network },
  { href: "/lab", label: "Simulation Lab", icon: FlaskConical },
  { href: "/recovery", label: "Recovery Command", icon: Wrench },
  { href: "/agents", label: "Agent Activity", icon: Bot },
  { href: "/audit", label: "Audit & Reports", icon: ScrollText },
];

/** Required on every screen, word for word (master prompt, docs/SECURITY.md §1). */
export const SIMULATION_NOTICE = "SIMULATION ENVIRONMENT — NOT CONNECTED TO LIVE INFRASTRUCTURE";

/** The dealt mark (taste-skill "dots"), the same shape the landing page uses. */
export function Mark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden className={cn("size-5 shrink-0 fill-focus", className)}>
      <circle cx="6.5" cy="6.5" r="4.5" />
      <circle cx="17.5" cy="6.5" r="4.5" />
      <circle cx="6.5" cy="17.5" r="4.5" />
      <rect x="13" y="13" width="9" height="9" rx="1.5" />
    </svg>
  );
}

function SimulationBanner() {
  return (
    <div
      role="note"
      aria-label="Simulation environment notice"
      data-testid="simulation-banner"
      className="flex min-h-7 shrink-0 items-center justify-center gap-2 border-b border-warn/30 bg-warn/10 px-3 text-center text-[13px] font-medium text-warn"
    >
      <span aria-hidden className="size-1.5 rounded-full bg-warn" />
      {SIMULATION_NOTICE}
    </div>
  );
}

function Brand() {
  return (
    <Link href="/" className="flex items-center gap-2 rounded-sm" aria-label="AFTERMATH product page">
      <Mark />
      <span className="text-[18px] font-medium">AFTERMATH</span>
    </Link>
  );
}

function UserMenu({ session }: { session: Session }) {
  const client = useQueryClient();
  return (
    <div className="flex items-center gap-3 text-[13px]" data-testid="user-menu">
      <span className="hidden items-center gap-2 sm:flex">
        <span className="font-medium">{session.user.display_name}</span>
        <span
          className="rounded-sm border border-line-strong px-1.5 font-mono text-[13px] text-muted"
          data-testid="user-role"
        >
          {session.user.role}
        </span>
      </span>
      <button
        type="button"
        onClick={() => {
          clearSession();
          client.clear();
        }}
        className="btn btn-secondary btn-sm"
      >
        <LogOut aria-hidden />
        Sign out
      </button>
    </div>
  );
}

function ConnectionStatus() {
  const { data, isError, isPending } = useSystemStatus();
  const state = isPending ? "connecting" : isError ? "offline" : "online";
  const color = { connecting: "bg-inactive", offline: "bg-crit", online: "bg-ok" }[state];
  return (
    <div className="flex items-center gap-4 text-[13px] text-muted">
      {data?.dataset && (
        <span className="hidden font-mono lg:inline" title={data.dataset.content_hash}>
          {data.dataset.name} {data.dataset.version}
        </span>
      )}
      <span className="flex items-center gap-1.5" aria-live="polite">
        <span aria-hidden className={cn("size-2 rounded-full", color)} />
        API {state}
      </span>
    </div>
  );
}

function Header({ children }: { children?: ReactNode }) {
  return (
    <header className="shrink-0 border-b border-line bg-bg">
      <SimulationBanner />
      <div className="flex h-14 items-center justify-between gap-4 px-5">
        <Brand />
        <div className="flex items-center gap-5">{children}</div>
      </div>
    </header>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  const session = useSession();
  // `undefined` = server render / hydration, where the session is not knowable. The page segment
  // is still rendered (Next validates it); the API client sends nothing without a session.
  if (session === null) {
    return (
      <div className="flex h-dvh flex-col overflow-hidden">
        <Header />
        <main className="min-h-0 flex-1 overflow-auto">
          <SignIn />
        </main>
      </div>
    );
  }
  return <SignedInShell session={session}>{children}</SignedInShell>;
}

function SignedInShell({ session, children }: { session: Session | undefined; children: ReactNode }) {
  const pathname = usePathname();
  return (
    <div className="flex h-dvh flex-col overflow-hidden">
      <Header>
        <ConnectionStatus />
        {session && <UserMenu session={session} />}
      </Header>
      <div className="flex min-h-0 flex-1 flex-col md:flex-row">
        <nav
          aria-label="Primary"
          className="flex shrink-0 gap-0.5 overflow-x-auto border-b border-line bg-bg px-2 py-2 md:w-56 md:flex-col md:border-r md:border-b-0 md:px-3 md:py-4"
        >
          {NAV.map(({ href, label, icon: Icon }) => {
            const active = pathname.startsWith(href);
            return (
              <Link
                key={href}
                href={href}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "relative flex shrink-0 items-center gap-2.5 rounded-md px-3 py-2 text-[14px] text-muted transition-colors duration-150 hover:bg-panel hover:text-fg",
                  active &&
                    "bg-panel text-fg before:absolute before:inset-y-2 before:left-0 before:w-0.5 before:rounded-full before:bg-focus",
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
