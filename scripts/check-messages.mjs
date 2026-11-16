#!/usr/bin/env node
/**
 * PRD AC 19 and design.md 18.3, 23.3: the three message files have the same keys, the same ICU
 * arguments and select options, no empty values, no em or en dashes, no Devanagari digits, no banned
 * phrases, and every key the code uses exists.
 */
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = join(fileURLToPath(new URL('.', import.meta.url)), '..');
const WEB = join(ROOT, 'apps', 'web');
const LOCALES = ['en', 'mr', 'hi'];
const errors = [];
const warnings = [];

const files = Object.fromEntries(LOCALES.map((l) => [l, JSON.parse(readFileSync(join(WEB, 'messages', `${l}.json`), 'utf8'))]));

/** Parse ICU into argument names and select/plural option keys (mirrors lib/icu.ts). */
function analyse(msg) {
  const args = new Set();
  const options = {};
  let i = 0;
  const s = msg;
  function message(end) {
    while (i < s.length) {
      const c = s[i];
      if (end && c === end) return;
      if (c === "'" && s[i + 1] === "'") { i += 2; continue; }
      if (c === '{') { argument(); continue; }
      if (c === '}') throw new Error(`unbalanced } at ${i}`);
      i++;
    }
    if (end) throw new Error('unterminated option');
  }
  function ident() {
    while (/\s/.test(s[i] ?? '')) i++;
    const st = i;
    while (i < s.length && /[^\s,{}]/.test(s[i])) i++;
    return s.slice(st, i);
  }
  function argument() {
    i++;
    const name = ident();
    while (/\s/.test(s[i] ?? '')) i++;
    args.add(name);
    if (s[i] === '}') { i++; return; }
    if (s[i] !== ',') throw new Error(`expected , after ${name}`);
    i++;
    const kind = ident();
    while (/\s/.test(s[i] ?? '')) i++;
    if (s[i] !== ',') throw new Error(`expected , after ${kind}`);
    i++;
    if (kind !== 'plural' && kind !== 'select') throw new Error(`unsupported type ${kind}`);
    const keys = [];
    for (;;) {
      while (/\s/.test(s[i] ?? '')) i++;
      if (s[i] === '}') { i++; break; }
      const key = ident();
      while (/\s/.test(s[i] ?? '')) i++;
      if (s[i] !== '{') throw new Error(`expected { after option ${key}`);
      i++;
      message('}');
      i++;
      keys.push(key);
    }
    if (kind === 'plural' && !keys.includes('other')) throw new Error(`plural ${name} has no other`);
    if (kind === 'select' && !keys.includes('other')) throw new Error(`select ${name} has no other`);
    options[`${name}:${kind}`] = kind === 'select' ? keys.sort().join(',') : 'plural';
  }
  message();
  return { args: [...args].sort().join(','), options };
}

const enKeys = Object.keys(files.en);
for (const l of LOCALES) {
  const keys = Object.keys(files[l]);
  const missing = enKeys.filter((k) => !(k in files[l]));
  const extra = keys.filter((k) => !(k in files.en));
  if (missing.length) errors.push(`${l}.json is missing ${missing.length} key(s): ${missing.slice(0, 10).join(', ')}${missing.length > 10 ? ' ...' : ''}`);
  if (extra.length) errors.push(`${l}.json has ${extra.length} extra key(s): ${extra.slice(0, 10).join(', ')}`);
  for (const [k, v] of Object.entries(files[l])) {
    if (typeof v !== 'string' || !v.trim()) { errors.push(`${l}.json ${k}: empty or not a string`); continue; }
    if (v.includes(String.fromCharCode(0x2014))) errors.push(`${l}.json ${k}: contains an em dash`);
    if (v.includes(String.fromCharCode(0x2013))) errors.push(`${l}.json ${k}: contains an en dash`);
    if (/[०-९]/.test(v)) errors.push(`${l}.json ${k}: Devanagari digits (use Western digits, design.md 7.5)`);
    try { analyse(v); } catch (e) { errors.push(`${l}.json ${k}: ICU syntax: ${e.message}`); }
  }
}
for (const k of enKeys) {
  let ref;
  try { ref = analyse(files.en[k]); } catch { continue; }
  for (const l of ['mr', 'hi']) {
    if (!(k in files[l])) continue;
    let got;
    try { got = analyse(files[l][k]); } catch { continue; }
    if (got.args !== ref.args) errors.push(`${l}.json ${k}: arguments {${got.args}} differ from en {${ref.args}}`);
    for (const [opt, keys] of Object.entries(ref.options)) {
      if (got.options[opt] !== keys) errors.push(`${l}.json ${k}: ${opt} options differ from en`);
    }
  }
}

const BANNED = [/will happen/i, /guaranteed/i, /road (is |will be )?closed/i, /road (is |will be )?blocked/i];
for (const [k, v] of Object.entries(files.en)) for (const re of BANNED) if (re.test(v)) errors.push(`en.json ${k}: banned phrase ${re}`);

// Every key used in code must exist.
const used = new Set();
const prefixes = new Set();
function walk(dir) {
  for (const name of readdirSync(dir)) {
    if (name === 'node_modules' || name === '.next' || name.startsWith('.')) continue;
    const p = join(dir, name);
    if (statSync(p).isDirectory()) { walk(p); continue; }
    if (!/\.(tsx?|mjs)$/.test(name) || /\.test\.tsx?$/.test(name)) continue;
    const src = readFileSync(p, 'utf8');
    for (const m of src.matchAll(/\bt\(\s*'([a-zA-Z0-9_.]+)'/g)) used.add(m[1]);
    for (const m of src.matchAll(/\bt\(\s*`([a-zA-Z0-9_.]+)\$\{/g)) prefixes.add(m[1]);
  }
}
for (const d of ['app', 'components', 'lib']) walk(join(WEB, d));
for (const k of used) if (!(k in files.en)) errors.push(`code uses missing key ${k}`);
for (const p of prefixes) if (!enKeys.some((k) => k.startsWith(p))) errors.push(`code uses dynamic key prefix ${p} with no matching keys`);

if (warnings.length) for (const w of warnings) console.warn(`warning: ${w}`);
if (errors.length) {
  console.error(`Message check failed with ${errors.length} error(s):`);
  for (const e of errors) console.error(`  ${e}`);
  process.exit(1);
}
console.log(`Messages OK: ${enKeys.length} keys in en, mr, hi; ${used.size} static keys and ${prefixes.size} dynamic prefixes used in code all resolve.`);
