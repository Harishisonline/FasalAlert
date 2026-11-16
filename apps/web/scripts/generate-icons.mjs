#!/usr/bin/env node
/**
 * Draws the FasalAlert logo mark (design.md 5.2) and exports the PWA icons (design.md 5.3) with a tiny
 * software rasteriser: 4x4 supersampled coverage of a rounded square, round-capped strokes and the
 * dashed threshold line, encoded as PNG with node:zlib. No image libraries and no generated imagery.
 */
import { deflateSync } from 'node:zlib';
import { mkdirSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const OUT = join(dirname(fileURLToPath(import.meta.url)), '..', 'public', 'icons');
const LEAF = [0x0b, 0x5c, 0x2e];
const WHITE = [0xff, 0xff, 0xff];
const STROKE = 2.5;

function cubic(p0, p1, p2, p3, n = 40) {
  const pts = [];
  for (let i = 0; i <= n; i++) {
    const t = i / n, u = 1 - t;
    pts.push([
      u * u * u * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t * t * t * p3[0],
      u * u * u * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t * t * t * p3[1],
    ]);
  }
  return pts;
}

// The mark on its 48 grid (same paths as components/Icon/LogoMark.tsx).
const polylines = [
  [[24, 38], [24, 21]],
  [...cubic([24, 25], [22.5, 19.5], [18, 16], [12, 16.5]), ...cubic([12, 16.5], [12.5, 22], [17, 25.5], [24, 25])],
  [...cubic([24, 21.5], [25.5, 15.5], [30.5, 12], [36, 12.5]), ...cubic([36, 12.5], [36, 18], [31.5, 22], [24, 21.5])],
];
const dashes = [];
for (let x = 10; x < 38; x += 5) dashes.push([x, Math.min(x + 3, 38)]);

function distToSegment(px, py, [ax, ay], [bx, by]) {
  const dx = bx - ax, dy = by - ay;
  const len2 = dx * dx + dy * dy;
  const t = len2 ? Math.max(0, Math.min(1, ((px - ax) * dx + (py - ay) * dy) / len2)) : 0;
  const x = ax + t * dx - px, y = ay + t * dy - py;
  return Math.sqrt(x * x + y * y);
}

function inRoundRect(x, y, x0, y0, x1, y1, r) {
  if (x < x0 || x > x1 || y < y0 || y > y1) return false;
  const cx = Math.min(Math.max(x, x0 + r), x1 - r);
  const cy = Math.min(Math.max(y, y0 + r), y1 - r);
  return (x - cx) ** 2 + (y - cy) ** 2 <= r * r;
}

function symbolAt(gx, gy, withLine) {
  if (withLine && Math.abs(gy - 30) <= STROKE / 2 && dashes.some(([a, b]) => gx >= a && gx <= b)) return true;
  for (const pl of polylines) for (let i = 0; i < pl.length - 1; i++) if (distToSegment(gx, gy, pl[i], pl[i + 1]) <= STROKE / 2) return true;
  return false;
}

/**
 * mode 'full': full-bleed leaf background, the 40x40 container mapped to the whole canvas.
 * mode 'maskable': full-bleed background, the container inset 14% so the symbol sits in the 80% safe zone.
 * mode 'rounded': transparent canvas with the rounded container (favicon).
 */
function render(size, mode) {
  const ss = 4;
  const data = Buffer.alloc(size * size * 4);
  const inset = mode === 'maskable' ? 0.14 : 0;
  const withLine = size >= 32;
  for (let py = 0; py < size; py++) {
    for (let px = 0; px < size; px++) {
      let bg = 0, fg = 0;
      for (let sy = 0; sy < ss; sy++) for (let sx = 0; sx < ss; sx++) {
        const u = (px + (sx + 0.5) / ss) / size;
        const v = (py + (sy + 0.5) / ss) / size;
        let gx, gy;
        if (mode === 'rounded') { gx = u * 48; gy = v * 48; }
        else { gx = 4 + ((u - inset) / (1 - 2 * inset)) * 40; gy = 4 + ((v - inset) / (1 - 2 * inset)) * 40; }
        const inside = mode === 'rounded' ? inRoundRect(gx, gy, 4, 4, 44, 44, 10) : true;
        if (!inside) continue;
        bg++;
        if (symbolAt(gx, gy, withLine)) fg++;
      }
      const n = ss * ss;
      const a = bg / n;
      const f = bg ? fg / bg : 0;
      const i = (py * size + px) * 4;
      for (let c = 0; c < 3; c++) data[i + c] = Math.round(LEAF[c] * (1 - f) + WHITE[c] * f);
      data[i + 3] = Math.round(a * 255);
    }
  }
  return png(size, size, data);
}

const CRC = new Uint32Array(256).map((_, n) => { let c = n; for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1; return c >>> 0; });
function crc32(buf) { let c = 0xffffffff; for (const b of buf) c = CRC[(c ^ b) & 0xff] ^ (c >>> 8); return (c ^ 0xffffffff) >>> 0; }
function chunk(type, body) {
  const len = Buffer.alloc(4); len.writeUInt32BE(body.length);
  const tb = Buffer.from(type, 'ascii');
  const crc = Buffer.alloc(4); crc.writeUInt32BE(crc32(Buffer.concat([tb, body])));
  return Buffer.concat([len, tb, body, crc]);
}
function png(w, h, rgba) {
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(w, 0); ihdr.writeUInt32BE(h, 4); ihdr[8] = 8; ihdr[9] = 6; ihdr[10] = 0; ihdr[11] = 0; ihdr[12] = 0;
  const raw = Buffer.alloc((w * 4 + 1) * h);
  for (let y = 0; y < h; y++) { raw[y * (w * 4 + 1)] = 0; rgba.copy(raw, y * (w * 4 + 1) + 1, y * w * 4, (y + 1) * w * 4); }
  return Buffer.concat([Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]), chunk('IHDR', ihdr), chunk('IDAT', deflateSync(raw, { level: 9 })), chunk('IEND', Buffer.alloc(0))]);
}
function ico(pngBuf, size) {
  const header = Buffer.alloc(6); header.writeUInt16LE(0, 0); header.writeUInt16LE(1, 2); header.writeUInt16LE(1, 4);
  const entry = Buffer.alloc(16);
  entry[0] = size; entry[1] = size; entry[2] = 0; entry[3] = 0; entry.writeUInt16LE(1, 4); entry.writeUInt16LE(32, 6);
  entry.writeUInt32LE(pngBuf.length, 8); entry.writeUInt32LE(22, 12);
  return Buffer.concat([header, entry, pngBuf]);
}

const SVG = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48" width="48" height="48">
  <rect x="4" y="4" width="40" height="40" rx="10" fill="#0b5c2e"/>
  <g fill="none" stroke="#ffffff" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
    <path d="M10 30H38" stroke-dasharray="3 2" stroke-linecap="butt"/>
    <path d="M24 38V21"/>
    <path d="M24 25C22.5 19.5 18 16 12 16.5c.5 5.5 5 9 12 8.5z"/>
    <path d="M24 21.5c1.5-6 6.5-9.5 12-9 0 5.5-4.5 9.5-12 9z"/>
  </g>
</svg>
`;

mkdirSync(OUT, { recursive: true });
writeFileSync(join(OUT, 'icon-192.png'), render(192, 'full'));
writeFileSync(join(OUT, 'icon-512.png'), render(512, 'full'));
writeFileSync(join(OUT, 'icon-maskable-512.png'), render(512, 'maskable'));
writeFileSync(join(OUT, 'apple-touch-icon.png'), render(180, 'full'));
writeFileSync(join(OUT, 'icon.svg'), SVG);
writeFileSync(join(OUT, '..', 'favicon.ico'), ico(render(32, 'rounded'), 32));
console.log('icons written to', OUT);
