// Snapshot read-only demo fixtures from a running API (demo mode reads them when
// NEXT_PUBLIC_API_BASE_URL is unset):  node scripts/snapshot-fixtures.mjs http://localhost:8000
import { writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const base = (process.argv[2] ?? "http://localhost:8000").replace(/\/$/, "");
const out = fileURLToPath(new URL("../fixtures/", import.meta.url));

async function get(path) {
  const res = await fetch(base + path);
  if (!res.ok) throw new Error(`${path}: ${res.status}`);
  return res.json();
}

function save(name, data) {
  writeFileSync(out + name, JSON.stringify(data, null, 1) + "\n");
  console.log(`fixtures/${name}`);
}

const entities = await get("/entities");
save("entities.json", entities);
// The timeline fixture: the topic entity with the longest fact history.
const topics = entities.filter((e) => e.type === "topic").sort((a, b) => b.facts - a.facts);
const pick = topics.find((e) => /price toleran/i.test(e.name)) ?? topics[0];
save("timeline.json", await get(`/entities/${pick.id}/timeline`));

save("episodes.json", await get("/episodes"));
save("stats.json", await get("/stats"));
save("schema.json", await get("/schema"));
save("bindings.json", await get("/bindings"));
save("conflicts.json", await get("/conflicts"));
save("conflict_scan.json", await get("/conflict-scan"));
save("review_queue.json", await get("/review-queue"));
save("escalations.json", await get("/escalations?status="));
save("analytics.json", await get("/analytics"));
