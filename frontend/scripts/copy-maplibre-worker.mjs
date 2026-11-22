// MapLibre 6 loads its web worker from a URL next to its module; bundlers do not emit that file.
// Copy the installed version's worker into public/ (served same-origin, allowed by the CSP) and
// point MapLibre at it with setWorkerUrl (features/twin/TwinMap.tsx). Runs before dev and build.
import { copyFileSync, mkdirSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const pkg = dirname(require.resolve("maplibre-gl/package.json"));
const out = join(dirname(fileURLToPath(import.meta.url)), "..", "public", "vendor");
mkdirSync(out, { recursive: true });
copyFileSync(join(pkg, "dist", "maplibre-gl-worker.mjs"), join(out, "maplibre-gl-worker.mjs"));
console.log("maplibre worker -> public/vendor/maplibre-gl-worker.mjs");
