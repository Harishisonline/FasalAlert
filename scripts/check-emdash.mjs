#!/usr/bin/env node
/**
 * PRD AC 24: no em dash in any locale file, source file or rendered page.
 * Usage: node scripts/check-emdash.mjs [--base http://localhost:3000]
 * Without --base it scans files; with --base it also fetches every route in every locale.
 */
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { extname, join, relative } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = join(fileURLToPath(new URL('.', import.meta.url)), '..');
const EM = String.fromCharCode(0x2014);
const TEXT = new Set(['.ts', '.tsx', '.js', '.mjs', '.cjs', '.json', '.css', '.md', '.html', '.svg', '.txt', '.yml', '.yaml']);
const SKIP_DIRS = new Set(['node_modules', '.next', 'coverage', 'dist', 'out', '.turbo', 'maplibre']);
const TARGETS = ['apps/web', 'packages/shared', 'scripts', 'README.md'];

const hits = [];
function scan(path) {
  let st;
  try { st = statSync(path); } catch { return; }
  // AGENTS.md is written by `next dev` (not authored here) and is not published.
  if (path.endsWith('AGENTS.md')) return;
  if (st.isDirectory()) {
    const name = path.split('/').pop();
    if (SKIP_DIRS.has(name)) return;
    for (const entry of readdirSync(path)) scan(join(path, entry));
    return;
  }
  if (!TEXT.has(extname(path)) || st.size > 5_000_000) return;
  const text = readFileSync(path, 'utf8');
  if (!text.includes(EM)) return;
  text.split('\n').forEach((line, i) => { if (line.includes(EM)) hits.push(`${relative(ROOT, path)}:${i + 1}: ${line.trim().slice(0, 120)}`); });
}
let files = 0;
for (const t of TARGETS) { scan(join(ROOT, t)); files++; }

const args = process.argv.slice(2);
const baseIdx = args.indexOf('--base');
if (baseIdx >= 0 && args[baseIdx + 1]) {
  const base = args[baseIdx + 1].replace(/\/$/, '');
  const routes = ['/', '/?lang=en', '/?lang=hi'];
  for (const l of ['en', 'mr', 'hi']) {
    for (const r of ['signin', 'home', 'field/1', 'ask', 'alert', 'market', 'onboarding', 'settings', 'settings/calibration', 'offline', 'no-such-page']) routes.push(`/${l}/${r}`);
  }
  routes.push('/xx/unknown');
  for (const r of routes) {
    try {
      const res = await fetch(`${base}${r}`, { redirect: 'follow' });
      const html = await res.text();
      if (html.includes(EM)) hits.push(`rendered ${r}: contains an em dash`);
    } catch (e) {
      hits.push(`rendered ${r}: fetch failed (${e.message})`);
    }
  }
  console.log(`checked ${routes.length} rendered pages`);
}

if (hits.length) {
  console.error(`Em dash (U+2014) found in ${hits.length} place(s):`);
  for (const h of hits) console.error(`  ${h}`);
  process.exit(1);
}
console.log(`No em dash found in ${TARGETS.join(', ')}.`);
