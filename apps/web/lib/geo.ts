/**
 * District boundaries for R1 (design.md 16.8). The backend provides
 * public/geo/mh-districts.geojson with a feature property `code`. When the file is missing the
 * map renders its honest error state: geometry is never fabricated.
 */
import { promises as fs } from 'node:fs';
import path from 'node:path';

type Ring = [number, number][];
export interface DistrictShape { code: string; polygons: Ring[][] }
export interface GeoData { shapes: DistrictShape[]; bbox: [number, number, number, number] }
export interface SvgDistrict { code: string; d: string; cx: number; cy: number }
export interface SvgMap { width: number; height: number; districts: SvgDistrict[] }

const FILE = path.join(process.cwd(), 'public', 'geo', 'mh-districts.geojson');
export const GEO_URL = '/geo/mh-districts.geojson';

let cached: { mtime: number; data: GeoData | null } | null = null;

export async function loadDistrictGeo(): Promise<GeoData | null> {
  try {
    const stat = await fs.stat(FILE);
    if (cached && cached.mtime === stat.mtimeMs) return cached.data;
    const json = JSON.parse(await fs.readFile(FILE, 'utf8')) as {
      features?: { properties?: { code?: unknown }; geometry?: { type: string; coordinates: unknown } }[];
    };
    const shapes: DistrictShape[] = [];
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    for (const f of json.features ?? []) {
      const code = f.properties?.code;
      if (typeof code !== 'string' && typeof code !== 'number') continue;
      const g = f.geometry;
      if (!g) continue;
      const polys = (g.type === 'Polygon' ? [g.coordinates] : g.type === 'MultiPolygon' ? (g.coordinates as unknown[]) : []) as Ring[][];
      if (polys.length === 0) continue;
      for (const poly of polys) for (const ring of poly) for (const [x, y] of ring) {
        if (x < minX) minX = x; if (x > maxX) maxX = x; if (y < minY) minY = y; if (y > maxY) maxY = y;
      }
      shapes.push({ code: String(code), polygons: polys });
    }
    const data = shapes.length ? { shapes, bbox: [minX, minY, maxX, maxY] as GeoData['bbox'] } : null;
    cached = { mtime: stat.mtimeMs, data };
    return data;
  } catch {
    return null;
  }
}

/** Project to an SVG viewBox with an equirectangular projection scaled by cos(mid latitude). */
export function toSvg(geo: GeoData, width = 600): SvgMap {
  const [minX, minY, maxX, maxY] = geo.bbox;
  const k = Math.cos((((minY + maxY) / 2) * Math.PI) / 180);
  const sx = width / ((maxX - minX) * k);
  const height = Math.round((maxY - minY) * sx);
  const px = (x: number) => (x - minX) * k * sx;
  const py = (y: number) => (maxY - y) * sx;
  const districts = geo.shapes.map((s) => {
    let a = 0, cx = 0, cy = 0;
    const d = s.polygons.map((poly) => poly.map((ring) => {
      const pts = ring.map(([x, y]) => [px(x), py(y)] as const);
      for (let i = 0; i < pts.length - 1; i++) {
        const [x0, y0] = pts[i]!;
        const [x1, y1] = pts[i + 1]!;
        const c = x0 * y1 - x1 * y0;
        a += c; cx += (x0 + x1) * c; cy += (y0 + y1) * c;
      }
      return `M${pts.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join('L')}Z`;
    }).join('')).join('');
    const area = a / 2;
    return { code: s.code, d, cx: area ? cx / (6 * area) : 0, cy: area ? cy / (6 * area) : 0 };
  });
  return { width, height, districts };
}
