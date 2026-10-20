// Emits a Vercel Build Output API v3 tree at <repo>/.vercel/output:
//   static/            -> events-radar SPA (must be built beforehand)
//   functions/api.func -> Express app bundled into a single CJS file
// Bundling ourselves avoids Vercel's per-file TS compile, which does not
// handle the TS-source workspace packages (@workspace/db, @workspace/api-zod).
import path from "node:path";
import { fileURLToPath } from "node:url";
import { existsSync } from "node:fs";
import { cp, mkdir, rm, writeFile } from "node:fs/promises";
import { build } from "esbuild";

const artifactDir = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(artifactDir, "../..");
const outputDir = path.join(repoRoot, ".vercel", "output");
const funcDir = path.join(outputDir, "functions", "api.func");
const staticSrc = path.join(repoRoot, "artifacts", "events-radar", "dist", "public");

if (!existsSync(path.join(staticSrc, "index.html"))) {
  throw new Error(`Frontend build missing at ${staticSrc} — build @workspace/events-radar first`);
}

await rm(outputDir, { recursive: true, force: true });
await mkdir(funcDir, { recursive: true });

await build({
  entryPoints: [path.join(artifactDir, "src", "vercel.ts")],
  outfile: path.join(funcDir, "index.js"),
  platform: "node",
  target: "node22",
  format: "cjs",
  bundle: true,
  external: ["pg-native"],
  // Drops the pino-pretty worker transport from the logger.
  define: { "process.env.NODE_ENV": '"production"' },
  // Launcher accepts either a function export or `.default`; make it the former.
  footer: { js: "module.exports = module.exports.default;" },
  sourcemap: "linked",
  logLevel: "info",
});

await writeFile(
  path.join(funcDir, ".vc-config.json"),
  JSON.stringify(
    {
      runtime: "nodejs22.x",
      handler: "index.js",
      launcherType: "Nodejs",
      shouldAddHelpers: false,
      shouldAddSourcemapSupport: true,
    },
    null,
    2,
  ),
);

await cp(staticSrc, path.join(outputDir, "static"), { recursive: true });

await writeFile(
  path.join(outputDir, "config.json"),
  JSON.stringify(
    {
      version: 3,
      routes: [
        { src: "^/api(?:/.*)?$", dest: "/api" },
        { handle: "filesystem" },
        { src: "^/.*$", dest: "/index.html" },
      ],
    },
    null,
    2,
  ),
);

console.log(`Vercel output written to ${outputDir}`);
