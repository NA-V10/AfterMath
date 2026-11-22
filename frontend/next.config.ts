import type { NextConfig } from "next";

const API_ORIGIN = process.env.NEXT_PUBLIC_API_ORIGIN ?? "http://localhost:8000";
const DEV = process.env.NODE_ENV !== "production";

/** Content Security Policy: everything from this origin, API calls to the one backend, no framing.
 * 'unsafe-inline' scripts are needed by Next's inline bootstrap and the static product page;
 * dev adds eval and websockets for hot reload. MapLibre runs its workers from blob: URLs. */
const CSP = [
  "default-src 'self'",
  `script-src 'self' 'unsafe-inline'${DEV ? " 'unsafe-eval'" : ""}`,
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob:",
  "font-src 'self'",
  `connect-src 'self' ${API_ORIGIN}${DEV ? " ws: wss:" : ""}`,
  "worker-src 'self' blob:",
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "frame-ancestors 'none'",
].join("; ");

const SECURITY_HEADERS = [
  { key: "Content-Security-Policy", value: CSP },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Referrer-Policy", value: "no-referrer" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=(), payment=()" },
  { key: "X-Aftermath-Environment", value: "SIMULATION" },
];

const nextConfig: NextConfig = {
  output: "standalone", // the container image runs .next/standalone/server.js
  async headers() {
    return [{ source: "/:path*", headers: SECURITY_HEADERS }];
  },
  // "/" is the public product page: a static page built with the taste-skill kit
  // (public/landing), kept apart from the console's styles. The console lives under /command etc.
  async rewrites() {
    return [{ source: "/", destination: "/landing/index.html" }];
  },
  cacheComponents: true,
  partialPrefetching: true,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
