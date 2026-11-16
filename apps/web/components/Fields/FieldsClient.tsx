'use client';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useId, useMemo, useState } from 'react';
import type { Crop } from '@fasalalert/shared/api';
import { ChevronRight, CircleCheck, CropIcon, MapPin, Pencil, Search, Sprout, Trash2 } from '@/components/Icon';
import { useI18n } from '@/components/I18n';
import { RiskBadge } from '@/components/Risk/RiskBadge';
import { Banner } from '@/components/UI/Banner';
import { Button } from '@/components/UI/Button';
import { Dialog } from '@/components/UI/Dialog';
import { useToast } from '@/components/UI/Toast';
import { clientApi, goToSignIn } from '@/lib/client-api';
import { filterFields, type FieldCardData, type FieldRiskFilter, type FieldSort } from '@/lib/fields';
import { formatDateShort } from '@/lib/format';
import styles from './FieldsClient.module.css';

/** The My Fields list: search, crop and risk filters, sort, and open, edit and delete for every field. */
export function FieldsClient({ items, addedId, renderedAt }: { items: FieldCardData[]; addedId: number | null; renderedAt: string }) {
  const { t, locale } = useI18n();
  const router = useRouter();
  const toast = useToast();
  const id = useId();
  const [query, setQuery] = useState('');
  const [crop, setCrop] = useState<Crop | 'all'>('all');
  const [risk, setRisk] = useState<FieldRiskFilter>('all');
  const [sort, setSort] = useState<FieldSort>('risk');
  const [confirm, setConfirm] = useState<FieldCardData | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [removed, setRemoved] = useState<Set<number>>(new Set());
  const now = useMemo(() => new Date(renderedAt), [renderedAt]);

  const live = items.filter((f) => !removed.has(f.id));
  const crops = Array.from(new Set(live.map((f) => f.crop)));
  const shown = filterFields(live, { query, crop, risk, sort, locale });
  const narrowed = query.trim() !== '' || crop !== 'all' || risk !== 'all';

  const remove = async () => {
    if (!confirm || deleting) return;
    setDeleting(true);
    setDeleteError(null);
    const r = await clientApi(`fields/${confirm.id}`, { method: 'DELETE' });
    setDeleting(false);
    if (!r.ok) {
      if (r.status === 401) { goToSignIn(locale); return; }
      if (r.status === 404) { setRemoved((s) => new Set(s).add(confirm.id)); setConfirm(null); router.refresh(); return; }
      setDeleteError(r.kind === 'network' ? t('common.noConnection') : t('fields.deleteFailed'));
      return;
    }
    setRemoved((s) => new Set(s).add(confirm.id));
    toast(t('fields.deleted', { name: confirm.name }));
    setConfirm(null);
    router.refresh();
  };

  return (
    <div className={styles.wrap}>
      {addedId && live.some((f) => f.id === addedId) ? (
        <Banner variant="success">{t('fields.added')}</Banner>
      ) : null}
      <div className={styles.toolbar} role="search">
        <label className={styles.search}>
          <span className="visually-hidden">{t('fields.search')}</span>
          <Search size={20} aria-hidden="true" />
          <input type="search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder={t('fields.search')} autoComplete="off" />
        </label>
        <label className={styles.selectWrap}>
          <span className={styles.selectLabel}>{t('fields.filterCrop')}</span>
          <select value={crop} onChange={(e) => setCrop(e.target.value as Crop | 'all')}>
            <option value="all">{t('fields.allCrops')}</option>
            {crops.map((c) => <option key={c} value={c}>{t(`crop.${c}`)}</option>)}
          </select>
        </label>
        <label className={styles.selectWrap}>
          <span className={styles.selectLabel}>{t('fields.filterRisk')}</span>
          <select value={risk} onChange={(e) => setRisk(e.target.value as FieldRiskFilter)}>
            <option value="all">{t('fields.riskAll')}</option>
            <option value="atRisk">{t('fields.riskAtRisk')}</option>
            <option value="noRisk">{t('fields.riskNone')}</option>
            <option value="attention">{t('fields.riskAttention')}</option>
          </select>
        </label>
        <label className={styles.selectWrap}>
          <span className={styles.selectLabel}>{t('fields.sort')}</span>
          <select value={sort} onChange={(e) => setSort(e.target.value as FieldSort)}>
            <option value="risk">{t('fields.sortRisk')}</option>
            <option value="name">{t('fields.sortName')}</option>
            <option value="newest">{t('fields.sortNewest')}</option>
          </select>
        </label>
      </div>
      <p className={styles.count} aria-live="polite">{t('fields.showing', { shown: shown.length, total: live.length })}</p>

      {shown.length === 0 ? (
        <div className={styles.empty}>
          <p>{t('fields.noMatch')}</p>
          {narrowed ? <Button variant="text" onClick={() => { setQuery(''); setCrop('all'); setRisk('all'); }}>{t('map.clearFilters')}</Button> : null}
        </div>
      ) : (
        <ul className={styles.grid} aria-label={t('nav.myFields')}>
          {shown.map((f) => (
            <li key={f.id} className={styles.card} data-level={f.level} data-new={f.id === addedId || undefined}>
              <div className={styles.cardTop}>
                <span className={styles.cropIcon}><CropIcon crop={f.crop} size={32} duotone /></span>
                <div className={styles.titleBox}>
                  <h2 className={styles.name} id={`${id}-f${f.id}`}>
                    <Link href={`/${locale}/field/${f.id}`} className={styles.nameLink}>{f.name}</Link>
                  </h2>
                  <p className={styles.crop}>{[f.cropText, f.variety].filter(Boolean).join(' · ')}</p>
                </div>
                {f.status === 'decision' ? <RiskBadge level={f.level} size="sm" t={t} /> : null}
              </div>
              <dl className={styles.facts}>
                <div><dt><MapPin size={16} aria-hidden="true" /><span className="visually-hidden">{t('fields.location')}</span></dt><dd>{f.location ?? t('fields.locationPin')}</dd></div>
                <div><dt><Sprout size={16} aria-hidden="true" /><span className="visually-hidden">{t('fields.stage')}</span></dt><dd>{f.stage ?? t('field.stage.unknownShort')}</dd></div>
              </dl>
              <div className={styles.status} data-status={f.status}>
                {f.status === 'decision' && f.level === 'none' ? <CircleCheck size={18} aria-hidden="true" /> : null}
                <p>
                  {f.status === 'loading' ? t('fields.checking')
                    : f.status === 'pending' ? t('fields.pending')
                    : f.status === 'stale' ? t('fields.stale')
                      : f.status === 'abstain' ? (f.headline ?? t('fields.abstain'))
                        : f.headline}
                </p>
                {f.decisionDate ? <p className={styles.updated}>{t('fields.updated', { date: formatDateShort(f.decisionDate, locale, now) })}</p> : null}
              </div>
              <div className={styles.actions}>
                <Link href={`/${locale}/field/${f.id}`} className={styles.open} aria-describedby={`${id}-f${f.id}`}>
                  {t('fields.open')}<ChevronRight size={18} aria-hidden="true" />
                </Link>
                <Link href={`/${locale}/field/${f.id}?edit=details`} className={styles.iconAction} aria-label={t('fields.editNamed', { name: f.name })}>
                  <Pencil size={18} aria-hidden="true" /><span className={styles.actionText}>{t('field.edit')}</span>
                </Link>
                <button type="button" className={styles.iconAction} data-danger aria-label={t('fields.deleteNamed', { name: f.name })} onClick={() => { setDeleteError(null); setConfirm(f); }}>
                  <Trash2 size={18} aria-hidden="true" /><span className={styles.actionText}>{t('fields.delete')}</span>
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}

      <Dialog open={confirm !== null} title={confirm ? t('fields.deleteTitle', { name: confirm.name }) : ''} onCancel={() => { if (!deleting) setConfirm(null); }}
        actions={<>
          <Button variant="secondary" onClick={() => setConfirm(null)} disabled={deleting}>{t('common.cancel')}</Button>
          <Button variant="danger" loading={deleting} loadingLabel={t('fields.deleting')} onClick={() => void remove()}>{t('fields.deleteConfirm')}</Button>
        </>}>
        <p>{t('fields.deleteBody')}</p>
        {deleteError ? <p className={styles.error} role="alert">{deleteError}</p> : null}
      </Dialog>
    </div>
  );
}
