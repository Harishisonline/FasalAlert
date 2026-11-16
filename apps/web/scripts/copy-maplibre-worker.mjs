#!/usr/bin/env node
/** MapLibre v6 loads its worker from a URL; copy it next to the app's static files (design.md 16.1). */
import { copyFileSync, mkdirSync } from 'node:fs';
import { createRequire } from 'node:module';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const require = createRequire(import.meta.url);
const pkg = require.resolve('maplibre-gl/package.json');
const src = join(dirname(pkg), 'dist', 'maplibre-gl-worker.mjs');
const out = join(dirname(fileURLToPath(import.meta.url)), '..', 'public', 'maplibre');
mkdirSync(out, { recursive: true });
copyFileSync(src, join(out, 'maplibre-gl-worker.mjs'));
console.log('maplibre worker copied to', out);
