'use client';
import 'maplibre-gl/dist/maplibre-gl.css';
import { useEffect, useId, useRef, useState } from 'react';
import type { Map as MlMap, Marker as MlMarker } from 'maplibre-gl';
import { LocateFixed, Minus, Plus } from '@/components/Icon';
import { useI18n } from '@/components/I18n';
import { Disclosure } from '@/components/UI/Disclosure';
import { TextField } from '@/components/UI/Field';
import { formatCoordinate } from '@/lib/format';
import { MAHARASHTRA_BOUNDS, MAPLIBRE_WORKER_URL, prefersReducedMotion, webglSupported } from './webgl';
import { useLatest } from '@/lib/hooks';
import styles from './FieldPicker.module.css';

/** OpenFreeMap Positron: OSM data, no key, no registration (design.md 16.3). */
const BASEMAP_STYLE = 'https://tiles.openfreemap.org/styles/positron';
const STEP_10M = 10 / 111_320;

export interface LatLon { lat: number; lon: number }

function inMaharashtra(p: LatLon): boolean {
  const [[w, s], [e, n]] = MAHARASHTRA_BOUNDS;
  return p.lat >= s && p.lat <= n && p.lon >= w && p.lon <= e;
}

/**
 * FieldMapPicker (design.md 14.11): a draggable pin, tap-to-place, use-my-location and coordinate
 * inputs as the non-pointer alternative. `preview` mode is the small non-interactive pin preview.
 */
export function FieldPicker({ value, onChange, mode = 'pick', near, onReady }: {
  value: LatLon | null; onChange?: (p: LatLon) => void; mode?: 'pick' | 'preview'; near?: string | null; onReady?: (ok: boolean) => void;
}) {
  const { t, locale } = useI18n();
  const container = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MlMap | null>(null);
  const markerRef = useRef<MlMarker | null>(null);
  const onChangeRef = useLatest(onChange);
  const valueRef = useLatest(value);
  const onReadyRef = useLatest(onReady);
  const [state, setState] = useState<'loading' | 'ready' | 'unavailable'>('loading');
  const [geoMsg, setGeoMsg] = useState<string | null>(null);
  const [locating, setLocating] = useState(false);
  const [latText, setLatText] = useState(value ? String(value.lat.toFixed(5)) : '');
  const [lonText, setLonText] = useState(value ? String(value.lon.toFixed(5)) : '');
  const [coordErr, setCoordErr] = useState<string | null>(null);
  const [announce, setAnnounce] = useState('');
  const id = useId();

  const place = (p: LatLon, fromMap = true) => {
    onChangeRef.current?.(p);
    setLatText(p.lat.toFixed(5));
    setLonText(p.lon.toFixed(5));
    if (fromMap) setAnnounce(t('onb.map.pinMoved', { lat: formatCoordinate(p.lat, locale), lon: formatCoordinate(p.lon, locale) }));
  };

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const ml = await import('maplibre-gl');
      if (cancelled || !container.current) return;
      if (!navigator.onLine || !webglSupported()) { setState('unavailable'); onReadyRef.current?.(false); return; }
      ml.setWorkerUrl(MAPLIBRE_WORKER_URL);
      const start = valueRef.current;
      const map = new ml.Map({
        container: container.current,
        style: BASEMAP_STYLE,
        center: start ? [start.lon, start.lat] : [76.8, 19.2],
        zoom: start ? 13 : 5.5,
        maxBounds: MAHARASHTRA_BOUNDS,
        dragRotate: false,
        pitchWithRotate: false,
        touchPitch: false,
        interactive: mode === 'pick',
        cooperativeGestures: mode === 'pick' && window.matchMedia?.('(pointer: coarse)').matches ? true : undefined,
        attributionControl: { compact: true },
      });
      mapRef.current = map;
      map.touchZoomRotate.disableRotation();
      map.on('error', () => { if (!map.loaded()) { setState('unavailable'); onReadyRef.current?.(false); } });
      map.on('style.load', () => {
        // WebGL Devanagari shaping is not verified, so basemap labels stay Latin (design.md 16.3).
        for (const layer of map.getStyle().layers ?? []) {
          if (layer.type === 'symbol' && map.getLayoutProperty(layer.id, 'text-field') !== undefined) {
            map.setLayoutProperty(layer.id, 'text-field', ['coalesce', ['get', 'name:en'], ['get', 'name']]);
          }
        }
      });
      map.on('load', () => {
        if (cancelled) return;
        setState('ready');
        onReadyRef.current?.(true);
      });
      const el = document.createElement('div');
      el.className = styles.pin;
      el.innerHTML = '<svg width="32" height="40" viewBox="0 0 24 30" aria-hidden="true"><path d="M12 29s10-9.6 10-17A10 10 0 0 0 2 12c0 7.4 10 17 10 17z" fill="var(--color-action-primary)" stroke="var(--color-bg-surface)" stroke-width="1.5"/><circle cx="12" cy="12" r="3.6" fill="var(--color-bg-surface)"/></svg>';
      if (mode === 'pick') {
        el.tabIndex = 0;
        el.setAttribute('role', 'button');
        el.setAttribute('aria-label', t('onb.map.pin'));
        el.addEventListener('keydown', (e) => {
          const cur = markerRef.current?.getLngLat();
          if (!cur) return;
          const step = STEP_10M * (e.shiftKey ? 10 : 1);
          let { lat, lng } = cur;
          if (e.key === 'ArrowUp') lat += step;
          else if (e.key === 'ArrowDown') lat -= step;
          else if (e.key === 'ArrowLeft') lng -= step / Math.cos((lat * Math.PI) / 180);
          else if (e.key === 'ArrowRight') lng += step / Math.cos((lat * Math.PI) / 180);
          else return;
          e.preventDefault();
          markerRef.current?.setLngLat([lng, lat]);
          place({ lat, lon: lng });
        });
      }
      const marker = new ml.Marker({ element: el, draggable: mode === 'pick', anchor: 'bottom' });
      if (start) marker.setLngLat([start.lon, start.lat]).addTo(map);
      markerRef.current = marker;
      marker.on('dragstart', () => el.classList.add(styles.lifted));
      marker.on('dragend', () => {
        el.classList.remove(styles.lifted);
        const p = marker.getLngLat();
        place({ lat: p.lat, lon: p.lng });
      });
      if (mode === 'pick') {
        map.on('click', (e) => {
          marker.setLngLat(e.lngLat).addTo(map);
          place({ lat: e.lngLat.lat, lon: e.lngLat.lng });
        });
      }
    })().catch(() => { if (!cancelled) { setState('unavailable'); onReadyRef.current?.(false); } });
    return () => {
      cancelled = true;
      mapRef.current?.remove();
      mapRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode]);

  // Follow value changes from outside (village chosen, coordinates typed).
  useEffect(() => {
    const map = mapRef.current;
    const marker = markerRef.current;
    if (!map || !marker || !value) return;
    const cur = marker.getLngLat?.();
    if (!cur || Math.abs(cur.lat - value.lat) > 1e-7 || Math.abs(cur.lng - value.lon) > 1e-7) {
      marker.setLngLat([value.lon, value.lat]).addTo(map);
      map.easeTo({ center: [value.lon, value.lat], zoom: Math.max(map.getZoom(), 12), duration: prefersReducedMotion() ? 0 : 300 });
    }
  }, [value, state]);

  const locate = () => {
    if (!('geolocation' in navigator)) { setGeoMsg(t('onb.map.geoDenied')); return; }
    setLocating(true);
    setGeoMsg(null);
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        setLocating(false);
        const p = { lat: pos.coords.latitude, lon: pos.coords.longitude };
        if (!inMaharashtra(p)) { setGeoMsg(t('onb.map.geoDenied')); return; }
        place(p);
      },
      () => { setLocating(false); setGeoMsg(t('onb.map.geoDenied')); },
      { enableHighAccuracy: true, timeout: 15_000, maximumAge: 60_000 },
    );
  };

  const applyCoords = () => {
    const lat = Number(latText);
    const lon = Number(lonText);
    if (!Number.isFinite(lat) || !Number.isFinite(lon) || !inMaharashtra({ lat, lon })) { setCoordErr(t('onb.map.coordsInvalid')); return; }
    setCoordErr(null);
    place({ lat, lon }, false);
  };

  if (mode === 'preview') {
    return (
      <div className={styles.preview} aria-hidden="true">
        <div ref={container} className={styles.map} data-hidden={state !== 'ready' || undefined} />
        {state !== 'ready' ? <div className={styles.skeleton} /> : null}
      </div>
    );
  }

  return (
    <div className={styles.picker}>
      <div className={styles.mapWrap} role="region" aria-label={t('onb.map.label')}>
        <div ref={container} className={styles.map} data-hidden={state !== 'ready' || undefined} />
        {state === 'loading' ? <div className={styles.skeleton} aria-hidden="true" /> : null}
        {state === 'unavailable' ? <div className={styles.unavailable}><p>{t('onb.map.unavailable')}</p></div> : null}
        {state === 'ready' ? (
          <div className={styles.controls}>
            <button type="button" className={styles.control} aria-label={t('board.zoomIn')} onClick={() => mapRef.current?.zoomIn()}><Plus size={24} aria-hidden="true" /></button>
            <button type="button" className={styles.control} aria-label={t('board.zoomOut')} onClick={() => mapRef.current?.zoomOut()}><Minus size={24} aria-hidden="true" /></button>
          </div>
        ) : null}
      </div>
      <button type="button" className={styles.locate} onClick={locate} aria-busy={locating || undefined}>
        <LocateFixed size={24} aria-hidden="true" />
        <span>{locating ? t('onb.map.locating') : t('onb.map.useMyLocation')}</span>
      </button>
      {geoMsg ? <p className={styles.info} role="status">{geoMsg}</p> : null}
      <p className="visually-hidden" aria-live="polite">{announce}</p>
      {value ? (
        <div className={styles.near}>
          {near ? <p className={styles.nearName}>{t('onb.map.near', { place: near })}</p> : null}
          <p className={styles.coords}>{t('onb.map.coords', { lat: formatCoordinate(value.lat, locale), lon: formatCoordinate(value.lon, locale) })}</p>
        </div>
      ) : null}
      <Disclosure label={t('onb.map.enterCoords')} defaultOpen={state === 'unavailable'} key={state}>
        <div className={styles.coordInputs}>
          <TextField id={`${id}-lat`} label={t('onb.map.lat')} inputMode="decimal" value={latText} onChange={(e) => setLatText(e.target.value)} onBlur={applyCoords} size="md" />
          <TextField id={`${id}-lon`} label={t('onb.map.lon')} inputMode="decimal" value={lonText} onChange={(e) => setLonText(e.target.value)} onBlur={applyCoords} size="md" error={coordErr ?? undefined} />
        </div>
      </Disclosure>
    </div>
  );
}
