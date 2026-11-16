/**
 * Risk patterns, the non-colour channel (design.md 16.4). The same geometry is drawn into canvases
 * for MapLibre (addImage), as SVG <pattern>s for the static map, and as CSS for the legend.
 */
import type { DisplayLevel } from '@/lib/risk';

export type PatternKind = 'dots' | 'diagonal' | 'cross' | 'horizontal';
export interface PatternSpec { kind: PatternKind; step: number; width: number; strokeVar: string }

export const PATTERNS: Partial<Record<DisplayLevel, PatternSpec>> = {
  low: { kind: 'dots', step: 8, width: 2, strokeVar: '--pattern-light-stroke' },
  medium: { kind: 'diagonal', step: 8, width: 2, strokeVar: '--pattern-dark-stroke' },
  high: { kind: 'cross', step: 8, width: 2, strokeVar: '--pattern-light-stroke' },
  critical: { kind: 'cross', step: 5, width: 2, strokeVar: '--pattern-critical-stroke' },
  nodata: { kind: 'horizontal', step: 6, width: 1.5, strokeVar: '--pattern-nodata-stroke' },
};

export const FILL_VARS: Record<DisplayLevel, string> = {
  none: '--risk-none', low: '--risk-low', medium: '--risk-medium', high: '--risk-high', critical: '--risk-critical', nodata: '--risk-nodata',
};

/** Draw one tile of a pattern into a canvas (browser only). */
export function drawPatternTile(spec: PatternSpec, stroke: string, scale = 2): { width: number; height: number; data: Uint8Array } | null {
  const size = spec.step * 2;
  const px = size * scale;
  const canvas = document.createElement('canvas');
  canvas.width = px;
  canvas.height = px;
  const ctx = canvas.getContext('2d');
  if (!ctx) return null;
  ctx.scale(scale, scale);
  ctx.strokeStyle = stroke;
  ctx.fillStyle = stroke;
  ctx.lineWidth = spec.width;
  const s = spec.step;
  ctx.beginPath();
  if (spec.kind === 'dots') {
    for (let x = s / 2; x < size; x += s) for (let y = s / 2; y < size; y += s) { ctx.moveTo(x + 1, y); ctx.arc(x, y, spec.width / 2 + 0.2, 0, Math.PI * 2); }
    ctx.fill();
  } else {
    if (spec.kind === 'diagonal' || spec.kind === 'cross') {
      for (let k = -size; k <= size * 2; k += s) { ctx.moveTo(k, 0); ctx.lineTo(k + size, size); }
    }
    if (spec.kind === 'cross') {
      for (let k = -size; k <= size * 2; k += s) { ctx.moveTo(k, size); ctx.lineTo(k + size, 0); }
    }
    if (spec.kind === 'horizontal') {
      for (let y = s / 2; y < size; y += s) { ctx.moveTo(0, y); ctx.lineTo(size, y); }
    }
    ctx.stroke();
  }
  const img = ctx.getImageData(0, 0, px, px);
  return { width: px, height: px, data: new Uint8Array(img.data.buffer) };
}

export function cssVar(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}
