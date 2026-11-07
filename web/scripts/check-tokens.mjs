// Fails if a hex colour appears in web/ outside tailwind.config.ts (DESIGN.md §8).
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("..", import.meta.url));
const skip = new Set(["node_modules", ".next", "test-results", "playwright-report"]);
const allowed = new Set(["tailwind.config.ts"]);
const exts = /\.(tsx?|jsx?|mjs|css|json)$/;
const hex = /#[0-9a-fA-F]{3,8}\b/g;
const offenders = [];

function walk(dir) {
  for (const name of readdirSync(dir)) {
    if (skip.has(name)) continue;
    const p = join(dir, name);
    if (statSync(p).isDirectory()) walk(p);
    else if (exts.test(name) && !allowed.has(relative(root, p)) && name !== "package-lock.json") {
      readFileSync(p, "utf8").split("\n").forEach((line, i) => {
        for (const m of line.matchAll(hex)) offenders.push(`${relative(root, p)}:${i + 1} ${m[0]}`);
      });
    }
  }
}
walk(root);
if (offenders.length) {
  console.error("Hex colours outside the token file:\n" + offenders.join("\n"));
  process.exit(1);
}
console.log("token check passed");
