/**
 * Copies the rendered Archify artifacts into public/ so the "How it works" tab
 * can iframe them.
 *
 * They live in ../diagrams as the single source of truth and are copied rather
 * than committed twice — 2MB of generated HTML does not belong in two places in
 * the repo. public/diagrams is gitignored for the same reason.
 */
import { copyFileSync, mkdirSync, existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const from = join(here, "..", "..", "diagrams");
const to = join(here, "..", "public", "diagrams");

const files = ["chat-turn.html", "system.html", "ingest.html"];

mkdirSync(to, { recursive: true });

let copied = 0;
for (const file of files) {
  const src = join(from, file);
  if (!existsSync(src)) {
    console.warn(`[diagrams] missing ${src} — re-render it (see diagrams/README.md)`);
    continue;
  }
  copyFileSync(src, join(to, file));
  copied++;
}
console.log(`[diagrams] synced ${copied}/${files.length} into public/diagrams`);
