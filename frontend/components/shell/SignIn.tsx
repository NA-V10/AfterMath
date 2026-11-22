"use client";

import { useQueryClient } from "@tanstack/react-query";
import { LogIn } from "lucide-react";
import { useState, type FormEvent } from "react";

import { ApiError } from "@/lib/api";
import { signIn } from "@/lib/queries";

/** Shown instead of any screen until the user signs in. Every API call needs a token. */
export function SignIn() {
  const client = useQueryClient();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await signIn(username.trim(), password);
      client.clear(); // drop anything cached while signed out
    } catch (err) {
      setError(
        err instanceof ApiError && err.status === 401
          ? "Unknown user or wrong password."
          : err instanceof Error
            ? err.message
            : "Sign-in failed.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex h-full items-center justify-center p-6">
      <form
        onSubmit={submit}
        aria-label="Sign in"
        className="flex w-full max-w-sm flex-col gap-3 rounded-sm border border-line-strong bg-panel p-5"
      >
        <div>
          <h1 className="text-[15px] font-semibold">Sign in to AFTERMATH</h1>
          <p className="mt-1 text-[12px] text-muted">
            Roles decide what you can do: viewers read, operators plan and execute, approvers decide.
          </p>
        </div>
        <label className="flex flex-col gap-1 text-[12px]">
          Username
          <input
            name="username"
            autoComplete="username"
            required
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            className="rounded-sm border border-line-strong bg-bg px-2 py-1.5"
          />
        </label>
        <label className="flex flex-col gap-1 text-[12px]">
          Password
          <input
            name="password"
            type="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="rounded-sm border border-line-strong bg-bg px-2 py-1.5"
          />
        </label>
        {error && (
          <p role="alert" className="text-[12px] text-crit">
            {error}
          </p>
        )}
        <button
          type="submit"
          disabled={busy || !username || !password}
          className="flex items-center justify-center gap-1.5 rounded-sm bg-focus px-3 py-1.5 font-medium text-bg disabled:opacity-40"
        >
          <LogIn className="size-4" aria-hidden />
          {busy ? "Signing in…" : "Sign in"}
        </button>
        <p className="text-[11px] text-dim">
          Local demo accounts are created with <code className="font-mono">python -m app.cli seed-users</code>.
        </p>
      </form>
    </div>
  );
}
