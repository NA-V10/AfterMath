import type { NextConfig } from "next";

const nextConfig: NextConfig = {
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
