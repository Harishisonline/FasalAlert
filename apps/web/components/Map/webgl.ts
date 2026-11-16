/** maplibregl.supported() was removed, so check for a WebGL context directly (design.md 16.1). */
export function webglSupported(): boolean {
  try {
    const c = document.createElement('canvas');
    return Boolean(c.getContext('webgl2') || c.getContext('webgl'));
  } catch {
    return false;
  }
}

/** MapLibre v6 loads its worker from a URL. scripts/copy-maplibre-worker.mjs puts it in public/. */
export const MAPLIBRE_WORKER_URL = '/maplibre/maplibre-gl-worker.mjs';

/** Maharashtra bounding box plus about 10 percent (design.md 12.1, 16.2). Geography, not data. */
export const MAHARASHTRA_BOUNDS: [[number, number], [number, number]] = [[71.9, 15.0], [81.6, 22.7]];

export function prefersReducedMotion(): boolean {
  return typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
}
