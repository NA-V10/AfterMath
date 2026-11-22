import createClient from "openapi-fetch";

import { clearSession, getSession } from "@/lib/session";
import type { components, paths } from "@/types/api";

export type Schemas = components["schemas"];

/** Origin of the FastAPI backend. Paths in the generated contract already include /api/v1. */
export const API_ORIGIN = process.env.NEXT_PUBLIC_API_ORIGIN ?? "http://localhost:8000";

export const api = createClient<paths>({ baseUrl: API_ORIGIN });

/** Attach the bearer token to every call; a 401 means the session is gone (expired/revoked). */
api.use({
  onRequest({ request }) {
    const session = getSession();
    if (session) request.headers.set("Authorization", `Bearer ${session.token}`);
    else if (!request.url.endsWith("/auth/token")) {
      // Not signed in: don't send a request that can only be refused.
      throw new ApiError(401, null, null, "Sign in to use AFTERMATH.");
    }
    return request;
  },
  onResponse({ request, response }) {
    if (response.status === 401 && !request.url.endsWith("/auth/token")) clearSession();
    return response;
  },
});

/** Headers for calls made outside openapi-fetch (streams, file downloads). */
export function authHeaders(): Record<string, string> {
  const session = getSession();
  return session ? { Authorization: `Bearer ${session.token}` } : {};
}

/** RFC 9457 problem details as produced by the backend. */
export interface Problem {
  type: string;
  title: string;
  status: number;
  detail: string;
  request_id?: string | null;
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly problem: Problem | null,
    readonly requestId: string | null,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }

  get isUnreachable(): boolean {
    return this.status === 0;
  }
}

function isProblem(value: unknown): value is Problem {
  return typeof value === "object" && value !== null && "title" in value && "status" in value;
}

/** Resolve an openapi-fetch call to its data, or throw a typed ApiError. */
export async function unwrap<T>(
  call: Promise<{ data?: T; error?: unknown; response: Response }>,
): Promise<T> {
  let result: { data?: T; error?: unknown; response: Response };
  try {
    result = await call;
  } catch (err) {
    if (err instanceof ApiError) throw err;
    throw new ApiError(0, null, null, `Cannot reach the AFTERMATH API at ${API_ORIGIN}.`);
  }
  const { data, error, response } = result;
  if (error !== undefined || data === undefined) {
    const problem = isProblem(error) ? error : null;
    throw new ApiError(
      response.status,
      problem,
      response.headers.get("x-request-id"),
      problem?.detail ?? `Request failed with status ${response.status}.`,
    );
  }
  return data;
}
