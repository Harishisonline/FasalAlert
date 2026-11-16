/**
 * Crop reference data from packages/shared/crops.json (PRD §8.2 "packages/shared ... crops"):
 * varieties, the typical sowing (or season start) date and its label. When the file cannot be read
 * the fallback carries only what the PRD itself states (§7.8: mango gives Alphonso, Keshar, Ratna,
 * Totapuri) and no sowing date, which hides the "typical window" checkbox (no invented dates).
 */
import { promises as fs } from 'node:fs';
import path from 'node:path';
import type { Crop, Localized } from '@fasalalert/shared/api';

export const CROPS: Crop[] = ['mango', 'pomegranate', 'grape', 'cotton', 'soybean', 'sugarcane'];

export interface CropVariety { key: string; name: Localized }
export interface CropInfo { varieties: CropVariety[]; typicalSowing: string | null; seasonLabel: Localized | null; seasonHint: Localized | null }
export type CropTable = Record<Crop, CropInfo>;

const name = (en: string): Localized => ({ en, mr: en, hi: en });
const empty = (): CropInfo => ({ varieties: [], typicalSowing: null, seasonLabel: null, seasonHint: null });
const PRD_FALLBACK: CropTable = {
  mango: { ...empty(), varieties: ['Alphonso', 'Keshar', 'Ratna', 'Totapuri'].map((v) => ({ key: v, name: name(v) })) },
  pomegranate: empty(), grape: empty(), cotton: empty(), soybean: empty(), sugarcane: empty(),
};

function isLocalized(v: unknown): v is Localized {
  return Boolean(v && typeof v === 'object' && 'en' in v);
}

let cache: CropTable | null = null;

export async function loadCropTable(): Promise<CropTable> {
  if (cache) return cache;
  const file = path.resolve(process.cwd(), '..', '..', 'packages', 'shared', 'crops.json');
  try {
    const raw = JSON.parse(await fs.readFile(file, 'utf8')) as { crops?: Record<string, Record<string, unknown>> };
    const table: CropTable = { ...PRD_FALLBACK };
    for (const crop of CROPS) {
      const entry = raw.crops?.[crop];
      if (!entry) continue;
      const varieties = Array.isArray(entry.varieties)
        ? (entry.varieties as unknown[]).flatMap((v): CropVariety[] => {
          if (typeof v === 'string') return [{ key: v, name: name(v) }];
          if (v && typeof v === 'object' && 'key' in v) {
            const o = v as { key: unknown; name?: unknown };
            return [{ key: String(o.key), name: isLocalized(o.name) ? o.name : name(String(o.key)) }];
          }
          return [];
        })
        : table[crop].varieties;
      const sd = entry.sowing_defaults as { month_day?: unknown } | undefined;
      const md = typeof sd?.month_day === 'string' && /^\d{2}-\d{2}$/.test(sd.month_day) ? sd.month_day : null;
      table[crop] = {
        varieties,
        typicalSowing: md,
        seasonLabel: isLocalized(entry.season_start_label) ? entry.season_start_label : null,
        seasonHint: isLocalized(entry.season_start_hint) ? entry.season_start_hint : null,
      };
    }
    cache = table;
  } catch {
    cache = PRD_FALLBACK;
  }
  return cache;
}

/** Display name of a stored variety (the API may store the key or the English name). */
export function varietyLabel(table: CropTable, crop: Crop, value: string | null | undefined, locale: keyof Localized): string | null {
  if (!value) return null;
  const v = table[crop]?.varieties.find((x) => x.key === value || x.name.en === value);
  return v ? v.name[locale] || v.name.en : value;
}
