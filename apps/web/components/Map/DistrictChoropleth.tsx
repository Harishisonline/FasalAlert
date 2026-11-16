'use client';
import 'maplibre-gl/dist/maplibre-gl.css';
import { useEffect, useRef, useState, type ReactNode } from 'react';
import type { Map as MlMap, Marker as MlMarker, GeoJSONSource } from 'maplibre-gl';
import { Maximize, Minus, Plus } from '@/components/Icon';
import type { DisplayLevel } from '@/lib/risk';
import { FILL_VARS, PATTERNS, cssVar, drawPatternTile } from './patterns';
import { MAPLIBRE_WORKER_URL, prefersReducedMotion, webglSupported } from './webgl';
import { useLatest } from '@/lib/hooks';
import styles from './DistrictChoropleth.module.css';

export type ChoroplethState = 'loading' | 'live' | 'stale' | 'api-down' | 'webgl-unavailable' | 'error';

export interface ChoroplethRow { code: string; level: DisplayLevel; name: string; rank?: number }

interface Props {
  rows: ChoroplethRow[];
  selectedCode: string | null;
  onSelect: (code: string | null) => void;
  geoUrl: string;
  geoAvailable: boolean;
  bbox: [number, number, number, number] | null;
  /** Static SVG map coloured with the live data (WebGL-unavailable fallback), server-rendered. */
  fallback: ReactNode;
  /** SVG skeleton from the same GeoJSON, shown until the WebGL map is ready. */
  skeleton: ReactNode;
  labels: { region: string; zoomIn: string; zoomOut: string; critical: (name: string) => string; webgl: string; error: string; geoMissing: string; reset: string };
  onRenderState?: (s: ChoroplethState) => void;
}

type Feature = { type: 'Feature'; properties: Record<string, unknown>; geometry: { type: string; coordinates: unknown } };
type FC = { type: 'FeatureCollection'; features: Feature[] };

function centroidOf(f: Feature): [number, number] | null {
  const polys = (f.geometry.type === 'Polygon' ? [f.geometry.coordinates] : f.geometry.type === 'MultiPolygon' ? f.geometry.coordinates : []) as [number, number][][][];
  let best: [number, number][] | null = null;
  let bestLen = 0;
  for (const p of polys) if (p[0] && p[0].length > bestLen) { best = p[0]; bestLen = p[0].length; }
  if (!best) return null;
  let sx = 0, sy = 0;
  for (const [x, y] of best) { sx += x; sy += y; }
  return [sx / best.length, sy / best.length];
}

/**
 * R1 district map (design.md 14.10, 16): MapLibre with no basemap, PRD risk fills, pattern overlay
 * via addImage, hover and selection via feature-state, Devanagari labels as HTML markers.
 */
export function DistrictChoropleth({ rows, selectedCode, onSelect, geoUrl, geoAvailable, bbox, fallback, skeleton, labels, onRenderState }: Props) {
  const container = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MlMap | null>(null);
  const geoRef = useRef<FC | null>(null);
  const markers = useRef<MlMarker[]>([]);
  const mlRef = useRef<typeof import('maplibre-gl') | null>(null);
  const hovered = useRef<string | null>(null);
  const selectedRef = useRef<string | null>(selectedCode);
  const onSelectRef = useLatest(onSelect);
  const rowsRef = useLatest(rows);
  const [state, setState] = useState<ChoroplethState>(geoAvailable ? 'loading' : 'error');
  const userMoved = useRef(false);

  useEffect(() => { onRenderState?.(state); }, [state, onRenderState]);

  const withLevels = (geo: FC): FC => {
    const byCode = new Map(rowsRef.current.map((r) => [r.code, r.level]));
    return { ...geo, features: geo.features.map((f) => ({ ...f, properties: { ...f.properties, level: byCode.get(String(f.properties.code)) ?? 'nodata' } })) };
  };

  // Create the map once.
  useEffect(() => {
    if (!geoAvailable) return;
    let cancelled = false;
    (async () => {
      const ml = await import('maplibre-gl');
      if (cancelled || !container.current) return;
      if (!webglSupported()) { setState('webgl-unavailable'); return; }
      mlRef.current = ml;
      ml.setWorkerUrl(MAPLIBRE_WORKER_URL);
      const res = await fetch(geoUrl);
      if (!res.ok) throw new Error('geo');
      const geo = (await res.json()) as FC;
      geoRef.current = geo;
      const fills = Object.fromEntries(Object.entries(FILL_VARS).map(([k, v]) => [k, cssVar(v)])) as Record<DisplayLevel, string>;
      const touch = window.matchMedia?.('(pointer: coarse)').matches;
      const b = bbox ?? [72.6, 15.6, 80.9, 22.1];
      // Generous pan limits: a tall phone-sized box needs vertical room to zoom out to the whole state (MAP-06).
      const padX = (b[2] - b[0]) * 0.5, padY = (b[3] - b[1]) * 1.2;
      const map = new ml.Map({
        container: container.current,
        style: { version: 8, sources: {}, layers: [{ id: 'bg', type: 'background', paint: { 'background-color': cssVar('--color-bg-canvas') } }] },
        bounds: [[b[0], b[1]], [b[2], b[3]]],
        fitBoundsOptions: { padding: 24 },
        minZoom: 4, // a narrow map box (phones, side-by-side layouts) needs room to show the whole state
        maxZoom: 9,
        maxBounds: [[b[0] - padX, b[1] - padY], [b[2] + padX, b[3] + padY]],
        dragRotate: false,
        pitchWithRotate: false,
        touchPitch: false,
        cooperativeGestures: touch ? true : undefined,
        attributionControl: false,
        renderWorldCopies: false,
      });
      mapRef.current = map;
      map.touchZoomRotate.disableRotation();
      map.keyboard.disableRotation();
      map.on('error', () => { if (!map.loaded()) setState('error'); });
      map.on('load', () => {
        if (cancelled) return;
        for (const [level, spec] of Object.entries(PATTERNS)) {
          if (!spec) continue;
          const img = drawPatternTile(spec, cssVar(spec.strokeVar), 2);
          if (img) map.addImage(`pat-${level}`, img, { pixelRatio: 2 });
        }
        map.addSource('districts', { type: 'geojson', data: withLevels(geo) as never, promoteId: 'code' });
        const levelMatch = (values: Record<string, string>, fallbackValue: string) =>
          ['match', ['get', 'level'], ...Object.entries(values).flat(), fallbackValue] as never;
        map.addLayer({ id: 'districts-fill', type: 'fill', source: 'districts', paint: { 'fill-color': levelMatch(fills, fills.nodata), 'fill-opacity': 0.85 } });
        map.addLayer({
          id: 'districts-pattern', type: 'fill', source: 'districts', filter: ['!=', ['get', 'level'], 'none'],
          paint: { 'fill-pattern': levelMatch({ low: 'pat-low', medium: 'pat-medium', high: 'pat-high', critical: 'pat-critical' }, 'pat-nodata') },
        });
        map.addLayer({ id: 'districts-line', type: 'line', source: 'districts', paint: { 'line-color': cssVar('--color-bg-surface'), 'line-width': 1 } });
        map.addLayer({
          id: 'districts-hover', type: 'line', source: 'districts',
          paint: { 'line-color': cssVar('--color-text-primary'), 'line-width': 1.5, 'line-opacity': ['case', ['boolean', ['feature-state', 'hover'], false], 1, 0] },
        });
        map.addLayer({
          id: 'districts-selected', type: 'line', source: 'districts',
          paint: { 'line-color': cssVar('--color-text-primary'), 'line-width': 3, 'line-opacity': ['case', ['boolean', ['feature-state', 'selected'], false], 1, 0] },
        });
        map.on('click', 'districts-fill', (e) => {
          const code = e.features?.[0]?.properties?.code;
          if (code === undefined) return;
          onSelectRef.current(String(code) === selectedRef.current ? null : String(code));
        });
        map.on('mousemove', 'districts-fill', (e) => {
          const code = e.features?.[0]?.properties?.code;
          if (code === undefined) return;
          if (hovered.current && hovered.current !== String(code)) map.setFeatureState({ source: 'districts', id: hovered.current }, { hover: false });
          hovered.current = String(code);
          map.setFeatureState({ source: 'districts', id: hovered.current }, { hover: true });
          map.getCanvas().style.cursor = 'pointer';
        });
        map.on('mouseleave', 'districts-fill', () => {
          if (hovered.current) map.setFeatureState({ source: 'districts', id: hovered.current }, { hover: false });
          hovered.current = null;
          map.getCanvas().style.cursor = '';
        });
        if (selectedRef.current) map.setFeatureState({ source: 'districts', id: selectedRef.current }, { selected: true });
        setState('live');
      });
    })().catch(() => { if (!cancelled) setState('error'); });
    return () => {
      cancelled = true;
      markers.current.forEach((m) => m.remove());
      markers.current = [];
      mapRef.current?.remove();
      mapRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [geoAvailable, geoUrl]);

  // Refresh fills without re-creating the map (design.md 16.6).
  useEffect(() => {
    const map = mapRef.current;
    const geo = geoRef.current;
    if (!map || !geo || state !== 'live') return;
    (map.getSource('districts') as GeoJSONSource | undefined)?.setData(withLevels(geo) as never);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- withLevels reads rowsRef; rows is the trigger
  }, [rows, state]);

  // Selection: feature-state, and pan only if out of view.
  useEffect(() => {
    const map = mapRef.current;
    const prev = selectedRef.current;
    selectedRef.current = selectedCode;
    if (!map || state !== 'live') return;
    if (prev && prev !== selectedCode) map.setFeatureState({ source: 'districts', id: prev }, { selected: false });
    if (selectedCode) {
      map.setFeatureState({ source: 'districts', id: selectedCode }, { selected: true });
      const f = geoRef.current?.features.find((x) => String(x.properties.code) === selectedCode);
      const c = f ? centroidOf(f) : null;
      if (c && !map.getBounds().contains(c)) map.easeTo({ center: c, duration: prefersReducedMotion() ? 0 : 300 });
    }
  }, [selectedCode, state]);

  // Keep the canvas in step with its box (docs/UX_QA_AUDIT.md MAP-04): the box changes size when the viewport
  // changes or a side panel opens. Until the user pans or zooms, the whole state stays in view.
  const fitAll = () => {
    const map = mapRef.current;
    if (!map || !bbox) return;
    map.fitBounds([[bbox[0], bbox[1]], [bbox[2], bbox[3]]], { padding: 16, duration: 0 });
  };
  useEffect(() => {
    const map = mapRef.current;
    const el = container.current;
    if (!map || !el || state !== 'live') return;
    const onMove = (e: { originalEvent?: unknown }) => { if (e.originalEvent) userMoved.current = true; };
    map.on('movestart', onMove);
    // The box may have changed size while the map was loading: fit once now.
    map.resize();
    if (!userMoved.current) fitAll();
    let frame = 0;
    const ro = new ResizeObserver(() => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        map.resize();
        if (!userMoved.current) fitAll();
      });
    });
    ro.observe(el);
    return () => { ro.disconnect(); cancelAnimationFrame(frame); map.off('movestart', onMove); };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- fitAll reads bbox, which is fixed per page
  }, [state]);

  // HTML markers: the top 3, the selected district, and a siren for critical districts (design.md 16.2, 16.5).
  useEffect(() => {
    const map = mapRef.current;
    const ml = mlRef.current;
    const geo = geoRef.current;
    if (!map || !ml || !geo || state !== 'live') return;
    markers.current.forEach((m) => m.remove());
    markers.current = [];
    for (const r of rows) {
      const isLabel = r.rank !== undefined || r.code === selectedCode;
      const isCritical = r.level === 'critical';
      if (!isLabel && !isCritical) continue;
      const f = geo.features.find((x) => String(x.properties.code) === r.code);
      const c = f ? centroidOf(f) : null;
      if (!c) continue;
      const el = document.createElement('div');
      el.className = styles.marker;
      if (isCritical) {
        const s = document.createElement('span');
        s.className = styles.siren;
        s.setAttribute('role', 'img');
        s.setAttribute('aria-label', labels.critical(r.name));
        s.innerHTML = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M7 18v-6a5 5 0 1 1 10 0v6"/><path d="M5 21a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-1a2 2 0 0 0-2-2H7a2 2 0 0 0-2 2z"/><path d="M21 12h1"/><path d="M18.5 4.5 18 5"/><path d="M2 12h1"/><path d="M12 2v1"/><path d="m4.929 4.929.707.707"/><path d="M12 12v6"/></svg>';
        el.appendChild(s);
      }
      if (isLabel) {
        const pill = document.createElement('span');
        pill.className = styles.pill;
        pill.dataset.selected = r.code === selectedCode ? 'true' : '';
        pill.textContent = r.rank !== undefined ? `${r.rank} ${r.name}` : r.name;
        el.appendChild(pill);
      }
      el.setAttribute('aria-hidden', isCritical ? 'false' : 'true');
      markers.current.push(new ml.Marker({ element: el, anchor: 'center' }).setLngLat(c).addTo(map));
    }
  }, [rows, selectedCode, state, labels]);

  const showFallback = state === 'webgl-unavailable';
  const showSkeleton = state === 'loading';
  return (
    <div className={styles.wrap} role="region" aria-label={labels.region}>
      <div ref={container} className={styles.map} data-hidden={state !== 'live' || undefined} />
      {showSkeleton ? <div className={styles.overlay}>{skeleton}</div> : null}
      {showFallback ? <div className={styles.overlay}>{fallback}</div> : null}
      {state === 'error' ? <div className={styles.overlayMessage}><p>{geoAvailable ? labels.error : labels.geoMissing}</p></div> : null}
      {state === 'live' ? (
        <div className={styles.controls}>
          <button type="button" className={styles.control} aria-label={labels.zoomIn} onClick={() => mapRef.current?.zoomIn({ duration: prefersReducedMotion() ? 0 : 200 })}><Plus size={24} aria-hidden="true" /></button>
          <button type="button" className={styles.control} aria-label={labels.zoomOut} onClick={() => mapRef.current?.zoomOut({ duration: prefersReducedMotion() ? 0 : 200 })}><Minus size={24} aria-hidden="true" /></button>
          <button type="button" className={styles.control} aria-label={labels.reset} title={labels.reset} onClick={() => { userMoved.current = false; fitAll(); }}><Maximize size={20} aria-hidden="true" /></button>
        </div>
      ) : null}
      {showFallback ? <p className={styles.note}>{labels.webgl}</p> : null}
    </div>
  );
}
