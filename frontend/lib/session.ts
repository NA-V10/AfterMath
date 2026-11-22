import { useSyncExternalStore } from "react";

import type { Schemas } from "@/lib/api";

/**
 * The signed-in session: a bearer token from POST /auth/token plus who it belongs to.
 *
 * Kept in sessionStorage (per tab, cleared when the tab closes) rather than localStorage, and
 * never in a cookie, so other sites cannot ride on it. The server re-checks the account and its
 * roles on every request; the role here only decides which buttons to show.
 */
export interface Session {
  token: string;
  expiresAt: string;
  user: Schemas["PrincipalOut"];
}

const KEY = "aftermath.session";
const listeners = new Set<() => void>();
let cached: Session | null | undefined;

function read(): Session | null {
  if (cached !== undefined) return cached;
  if (typeof window === "undefined") return null;
  try {
    const raw = window.sessionStorage.getItem(KEY);
    const parsed = raw ? (JSON.parse(raw) as Session) : null;
    cached = parsed && new Date(parsed.expiresAt).getTime() > Date.now() ? parsed : null;
  } catch {
    cached = null;
  }
  return cached;
}

function emit(): void {
  for (const l of listeners) l();
}

export function getSession(): Session | null {
  const s = read();
  if (s && new Date(s.expiresAt).getTime() <= Date.now()) {
    clearSession();
    return null;
  }
  return s;
}

export function setSession(s: Session): void {
  cached = s;
  try {
    window.sessionStorage.setItem(KEY, JSON.stringify(s));
  } catch {
    /* storage unavailable: keep the in-memory session for this page */
  }
  emit();
}

export function clearSession(): void {
  cached = null;
  try {
    window.sessionStorage.removeItem(KEY);
  } catch {
    /* ignore */
  }
  emit();
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** `undefined` until hydrated on the client, then the session or `null`. */
export function useSession(): Session | null | undefined {
  return useSyncExternalStore(
    subscribe,
    () => getSession(),
    () => undefined,
  );
}

const RANK = { viewer: 0, operator: 1, approver: 2, admin: 3 } as const;
export type Role = keyof typeof RANK;

/** Roles are cumulative (viewer < operator < approver < admin), as on the server. */
export function hasRole(session: Session | null | undefined, role: Role): boolean {
  const mine = (session?.user.role ?? "viewer") as Role;
  return (RANK[mine] ?? 0) >= RANK[role];
}
