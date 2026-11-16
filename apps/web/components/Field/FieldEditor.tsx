'use client';
import { useRouter } from 'next/navigation';
import { useEffect, useId, useRef, useState, useTransition, type ReactNode } from 'react';
import type { Crop, Field, Localized } from '@fasalalert/shared/api';
import { Pencil } from '@/components/Icon';
import { useI18n } from '@/components/I18n';
import { Button } from '@/components/UI/Button';
import { Dialog } from '@/components/UI/Dialog';
import { SelectField, TextField } from '@/components/UI/Field';
import { clientApi } from '@/lib/client-api';
import { areaFromSqm, areaToSqm, istDateKey } from '@/lib/format';
import { cropLabel, loc } from '@/lib/view';
import styles from './FieldEditor.module.css';

const CROPS: Crop[] = ['mango', 'pomegranate', 'grape', 'cotton', 'soybean', 'sugarcane'];

/**
 * Inline edit of name, crop, variety, sowing date and area (PRD §7.4, design.md 12.4, docs/UX_QA_AUDIT.md
 * FIELDS-01). Changing the crop asks first. After saving, the decision block shows "Recalculating your
 * decision" until the page reloads.
 */
export function FieldEditor({ field, varieties, summary, startOpen, actions, areaUnit }: {
  field: Pick<Field, 'id' | 'name' | 'crop' | 'variety' | 'sowing_date' | 'area_sqm'>; varieties: Record<Crop, { key: string; name: Localized }[]>; summary: ReactNode;
  startOpen?: 'sowing' | 'details' | null; actions: ReactNode; areaUnit: 'hectare' | 'acre';
}) {
  const { t, locale } = useI18n();
  const router = useRouter();
  const id = useId();
  const [open, setOpen] = useState(Boolean(startOpen));
  const [crop, setCrop] = useState<Crop>(field.crop);
  const [variety, setVariety] = useState(field.variety ?? '');
  const [sowing, setSowing] = useState(field.sowing_date ?? '');
  const [name, setName] = useState(field.name);
  const initialArea = field.area_sqm ? String(Number(areaFromSqm(field.area_sqm, areaUnit).toFixed(2))) : '';
  const [area, setArea] = useState(initialArea);
  const [confirm, setConfirm] = useState(false);
  const [error, setError] = useState<{ field: string; message: string } | null>(null);
  const [saving, setSaving] = useState(false);
  const [pending, start] = useTransition();
  const editBtn = useRef<HTMLButtonElement>(null);
  const sowingRef = useRef<HTMLInputElement>(null);
  const nameRef = useRef<HTMLInputElement>(null);
  const today = istDateKey(new Date());

  useEffect(() => {
    if (startOpen === 'sowing') sowingRef.current?.focus();
    if (startOpen === 'details') nameRef.current?.focus();
  }, [startOpen]);

  const save = async () => {
    if (sowing && sowing > today) { setError({ field: 'sowing_date', message: t('field.futureDate') }); return; }
    if (!name.trim()) { setError({ field: 'name', message: t('field.editForm.nameRequired') }); return; }
    if (area && !(Number(area) > 0)) { setError({ field: 'area_sqm', message: t('onb.areaInvalid') }); return; }
    setSaving(true);
    setError(null);
    const body: Record<string, unknown> = {};
    if (crop !== field.crop) body.crop = crop;
    if ((variety || null) !== (field.variety ?? null)) body.variety = variety || undefined;
    if ((sowing || null) !== (field.sowing_date ?? null) && sowing) body.sowing_date = sowing;
    if (name.trim() !== field.name) body.name = name.trim();
    if (area !== initialArea && area) body.area_sqm = Math.round(areaToSqm(Number(area), areaUnit));
    if (Object.keys(body).length === 0) { setOpen(false); return; }
    const r = await clientApi<Field>(`fields/${field.id}`, { method: 'PATCH', body });
    setSaving(false);
    if (!r.ok) {
      const f = String(r.error?.details?.field ?? '');
      setError({ field: f, message: r.error?.message || (r.kind === 'network' ? t('common.noConnection') : t('common.saveFailed')) });
      return;
    }
    setOpen(false);
    start(() => router.refresh());
    setTimeout(() => editBtn.current?.focus(), 50);
  };

  const onSubmit = () => {
    if (crop !== field.crop) setConfirm(true);
    else void save();
  };

  const list = varieties[crop] ?? [];
  return (
    <div className={styles.wrap}>
      {open ? (
        <form className={styles.form} onSubmit={(e) => { e.preventDefault(); onSubmit(); }} aria-labelledby={`${id}-t`}>
          <h2 id={`${id}-t`} className={styles.title}>{t('field.editForm.title')}</h2>
          <TextField ref={nameRef} id={`${id}-name`} label={t('onb.name')} value={name} maxLength={60} onChange={(e) => setName(e.target.value)} size="md"
            error={error?.field === 'name' ? error.message : undefined} />
          <SelectField id={`${id}-crop`} label={t('field.editForm.crop')} value={crop} onChange={(e) => { setCrop(e.target.value as Crop); setVariety(''); }} size="md"
            error={error?.field === 'crop' ? error.message : undefined}>
            {CROPS.map((c) => <option key={c} value={c}>{cropLabel(t, c)}</option>)}
          </SelectField>
          <SelectField id={`${id}-variety`} label={t('field.editForm.variety')} value={variety} onChange={(e) => setVariety(e.target.value)} size="md"
            error={error?.field === 'variety' ? error.message : undefined}>
            {list.map((v) => <option key={v.key} value={v.key}>{loc(v.name, locale)}</option>)}
            {variety && !list.some((v) => v.key === variety) ? <option value={variety}>{variety}</option> : null}
            <option value="">{t('field.notSure')}</option>
          </SelectField>
          <TextField ref={sowingRef} id={`${id}-sowing`} type="date" max={today} label={t('field.editForm.sowing')} value={sowing} onChange={(e) => setSowing(e.target.value)} size="md"
            error={error?.field === 'sowing_date' ? error.message : undefined} />
          <TextField id={`${id}-area`} label={`${t('onb.areaLabel')} (${areaUnit === 'acre' ? t('units.acre') : t('units.ha')})`} inputMode="decimal" value={area}
            onChange={(e) => setArea(e.target.value.replace(/[^\d.]/g, ''))} size="md" error={error?.field === 'area_sqm' ? error.message : undefined} />
          {error && !['name', 'crop', 'variety', 'sowing_date', 'area_sqm'].includes(error.field) ? <p className={styles.error} role="alert">{error.message}</p> : null}
          <div className={styles.actions}>
            <Button type="submit" loading={saving} loadingLabel={t('common.saving')}>{t('common.save')}</Button>
            <Button variant="secondary" onClick={() => { setOpen(false); setCrop(field.crop); setVariety(field.variety ?? ''); setSowing(field.sowing_date ?? ''); setName(field.name); setArea(initialArea); setError(null); setTimeout(() => editBtn.current?.focus(), 50); }}>{t('common.cancel')}</Button>
          </div>
        </form>
      ) : (
        <>
          {summary}
          <div className={styles.actions}>
            {actions}
            <Button ref={editBtn} variant="secondary" icon={<Pencil size={20} aria-hidden="true" />} onClick={() => setOpen(true)}>{t('field.edit')}</Button>
          </div>
        </>
      )}
      {pending ? <p className={styles.recalc} role="status">{t('field.editForm.recalculating')}</p> : null}
      <Dialog open={confirm} title={t('field.editForm.confirmCropTitle')} onCancel={() => setConfirm(false)}
        actions={<>
          <Button variant="secondary" onClick={() => setConfirm(false)}>{t('common.cancel')}</Button>
          <Button onClick={() => { setConfirm(false); void save(); }}>{t('field.editForm.change')}</Button>
        </>}>
        <p>{t('field.editForm.confirmCrop')}</p>
      </Dialog>
    </div>
  );
}
