'use client';
import { useEffect, useId, useRef, useState } from 'react';
import type { VillageSearchHit } from '@fasalalert/shared/api';
import { MapPin, Search, X } from '@/components/Icon';
import { useI18n } from '@/components/I18n';
import { FieldPicker, type LatLon } from '@/components/Map/FieldPicker';
import { Button } from '@/components/UI/Button';
import { clientApi } from '@/lib/client-api';
import { loc } from '@/lib/view';
import styles from './MapPinDialog.module.css';

/**
 * Optional exact-location picker (docs/UX_QA_AUDIT.md ONB-01). The map is only created when the farmer asks
 * for it. The pin is a draft until "Use this location"; Cancel and Escape leave the earlier choice untouched.
 */
export function MapPinDialog({ open, initial, onConfirm, onCancel }: { open: boolean; initial: LatLon | null; onConfirm: (p: LatLon) => void; onCancel: () => void }) {
  const { t, locale } = useI18n();
  const id = useId();
  const ref = useRef<HTMLDialogElement>(null);
  const [draft, setDraft] = useState<LatLon | null>(initial);
  const [q, setQ] = useState('');
  const [hits, setHits] = useState<VillageSearchHit[] | null>(null);
  const [searching, setSearching] = useState(false);
  const [searchFailed, setSearchFailed] = useState(false);

  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) d.showModal();
    else if (!open && d.open) d.close();
  }, [open]);

  useEffect(() => {
    const term = q.trim();
    if (term.length < 2) return;
    const ac = new AbortController();
    const timer = setTimeout(async () => {
      setSearching(true);
      try {
        const r = await clientApi<VillageSearchHit[]>('locations/search', { query: { q: term, limit: 8 }, signal: ac.signal });
        setHits(r.ok ? r.data : []);
        setSearchFailed(!r.ok);
      } catch { /* aborted by the next keystroke */ }
      setSearching(false);
    }, 250);
    return () => { clearTimeout(timer); ac.abort(); };
  }, [q]);

  return (
    <dialog ref={ref} className={styles.dialog} aria-labelledby={`${id}-t`} onCancel={(e) => { e.preventDefault(); onCancel(); }}>
      {open ? (
        <div className={styles.inner}>
          <header className={styles.head}>
            <h2 id={`${id}-t`} className={styles.title}>{t('onb.map.title')}</h2>
            <button type="button" className={styles.close} aria-label={t('common.cancel')} onClick={onCancel}><X size={24} aria-hidden="true" /></button>
          </header>
          <div className={styles.body}>
            <div className={styles.searchBox}>
              <label htmlFor={`${id}-q`} className={styles.label}>{t('onb.map.searchLabel')}</label>
              <div className={styles.search}>
                <Search size={20} aria-hidden="true" />
                <input id={`${id}-q`} type="search" value={q} onChange={(e) => { setQ(e.target.value); if (e.target.value.trim().length < 2) setHits(null); }}
                  placeholder={t('onb.map.searchPlaceholder')} autoComplete="off" aria-describedby={`${id}-qs`} />
              </div>
              <p id={`${id}-qs`} className={styles.status} aria-live="polite">
                {searching ? t('onb.map.searching') : searchFailed ? t('onb.couldNotLoad') : hits && hits.length === 0 ? t('onb.noMatches') : ''}
              </p>
              {hits && hits.length > 0 ? (
                <ul className={styles.hits}>
                  {hits.map((h) => (
                    <li key={h.id}>
                      <button type="button" className={styles.hit} onClick={() => {
                        if (typeof h.lat === 'number' && typeof h.lon === 'number') setDraft({ lat: h.lat, lon: h.lon });
                        setHits(null);
                        setQ(loc(h.name, locale));
                      }}>
                        <MapPin size={18} aria-hidden="true" />
                        <span><strong>{loc(h.name, locale)}</strong> <span className={styles.hitMeta}>{loc(h.taluka.name, locale)}, {loc(h.district.name, locale)}</span></span>
                      </button>
                    </li>
                  ))}
                </ul>
              ) : null}
            </div>
            <p className={styles.help}>{t('onb.map.help')}</p>
            <FieldPicker value={draft} onChange={setDraft} />
          </div>
          <footer className={styles.foot}>
            <Button variant="secondary" onClick={onCancel}>{t('common.cancel')}</Button>
            <Button disabled={!draft} onClick={() => { if (draft) onConfirm(draft); }}>{t('onb.map.use')}</Button>
          </footer>
        </div>
      ) : null}
    </dialog>
  );
}
