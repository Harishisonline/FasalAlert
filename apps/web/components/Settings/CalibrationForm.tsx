'use client';
import { usePathname, useRouter } from 'next/navigation';
import { useId, useState } from 'react';
import { useOnline } from '@/lib/hooks';
import type { Calibration, Crop } from '@fasalalert/shared/api';
import { CropIcon, ThermometerSnowflake, ThermometerSun } from '@/components/Icon';
import { useI18n } from '@/components/I18n';
import { Banner } from '@/components/UI/Banner';
import { Button } from '@/components/UI/Button';
import { ChipRadioGroup } from '@/components/UI/Chips';
import { Dialog } from '@/components/UI/Dialog';
import { SelectField } from '@/components/UI/Field';
import { Stepper } from '@/components/UI/Stepper';
import { clientApi } from '@/lib/client-api';
import { formatTemp, formatWithUnit } from '@/lib/format';
import { cropLabel } from '@/lib/view';
import styles from './CalibrationForm.module.css';

const SENS = ['low', 'normal', 'high'] as const;
type Sens = (typeof SENS)[number];

interface FormState { sensitivity: Sens; frost: number | null; heat: number | null; lead: number; mandi: string }

/** R9b per-field calibration (PRD §7.10, design.md 12.10). */
export function CalibrationForm({ fields, fieldId, crop, calibration, mandis, primaryMandi }: {
  fields: { id: number; name: string; crop: Crop }[]; fieldId: number; crop: Crop; calibration: Calibration;
  mandis: { name: string; distance_km: number | null }[]; primaryMandi: string | null;
}) {
  const { t, locale } = useI18n();
  const router = useRouter();
  const pathname = usePathname();
  const id = useId();
  const initial: FormState = {
    sensitivity: calibration.sensitivity,
    frost: calibration.frost_threshold_c ?? calibration.defaults.frost_threshold_c,
    heat: calibration.heat_threshold_c ?? calibration.defaults.heat_threshold_c,
    lead: calibration.harvest_lead_hours || 24,
    mandi: primaryMandi ?? '',
  };
  const [form, setForm] = useState<FormState>(initial);
  const [base, setBase] = useState<FormState>(initial);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [done, setDone] = useState(false);
  const [switchTo, setSwitchTo] = useState<number | null>(null);
  const online = useOnline();

  const d = calibration.defaults;
  const dirty = JSON.stringify(form) !== JSON.stringify(base);
  const fieldName = fields.find((f) => f.id === fieldId)?.name ?? '';
  const c = cropLabel(t, crop, true);
  const step = 0.5;

  const validate = (f: FormState): Record<string, string> => {
    const e: Record<string, string> = {};
    if (f.frost !== null && d.min_frost_c !== null && f.frost < d.min_frost_c) e.frost_threshold_c = t('calib.belowLimit', { value: formatTemp(d.min_frost_c, locale), crop: c, source: d.source });
    if (f.heat !== null && d.max_heat_c !== null && f.heat > d.max_heat_c) e.heat_threshold_c = t('calib.aboveLimit', { value: formatTemp(d.max_heat_c, locale), crop: c, source: d.source });
    if (f.lead < 6 || f.lead > 168) e.harvest_lead_hours = t('calib.leadRange');
    return e;
  };

  const save = async (): Promise<boolean> => {
    const e = validate(form);
    setErrors(e);
    if (Object.keys(e).length) {
      // The value returns to the last valid one (design.md 12.10).
      setForm((f) => ({ ...f, ...(e.frost_threshold_c ? { frost: base.frost } : {}), ...(e.heat_threshold_c ? { heat: base.heat } : {}) }));
      return false;
    }
    setSaving(true);
    setDone(false);
    const body = {
      sensitivity: form.sensitivity,
      frost_threshold_c: form.frost === d.frost_threshold_c ? null : form.frost,
      heat_threshold_c: form.heat === d.heat_threshold_c ? null : form.heat,
      harvest_lead_hours: form.lead,
    };
    const r = await clientApi<Calibration>(`fields/${fieldId}/calibration`, { method: 'PATCH', body });
    let ok = r.ok;
    if (!r.ok) {
      const f = String(r.error?.details?.field ?? 'save');
      setErrors({ [f]: r.error?.message || (r.kind === 'network' ? t('common.noConnection') : t('common.saveFailed')) });
    }
    // The primary mandi lives on the field row, so it is a second PATCH (Appendix B, Q8).
    if (ok && form.mandi !== base.mandi && form.mandi) {
      const m = await clientApi(`fields/${fieldId}`, { method: 'PATCH', body: { primary_mandi: form.mandi } });
      if (!m.ok) { ok = false; setErrors({ primary_mandi: t('common.saveFailed') }); }
    }
    setSaving(false);
    if (ok) { setBase(form); setDone(true); router.refresh(); }
    return ok;
  };

  const goField = (fid: number) => router.push(`${pathname}?field_id=${fid}`);
  const hours = calibration.lead_hours_by_sensitivity;
  const sIndex = SENS.indexOf(form.sensitivity);
  const preview = (value: number | null, def: number | null, kind: 'frost' | 'heat') => {
    if (value === null) return null;
    const lo = Math.min(value, def ?? value) - 4;
    const hi = Math.max(value, def ?? value) + 4;
    const pos = (v: number) => `${((v - lo) / (hi - lo)) * 100}%`;
    return (
      <div className={styles.preview} aria-hidden="true">
        <span className={styles.previewTrack} />
        {def !== null ? <span className={styles.previewDefault} style={{ left: pos(def) }}><span>ICAR {formatTemp(def, locale)}</span></span> : null}
        <span className={styles.previewLine} data-kind={kind} style={{ left: pos(value) }}><span>{formatTemp(value, locale)}</span></span>
      </div>
    );
  };

  return (
    <div className={styles.form}>
      {!online ? <p className={styles.offline} role="status">{t('common.offlineSettings')}</p> : null}
      <ChipRadioGroup label={t('market.fieldLabel')} value={String(fieldId)}
        onChange={(v) => { const fid = Number(v); if (fid === fieldId) return; if (dirty) setSwitchTo(fid); else goField(fid); }}
        options={fields.map((f) => ({ value: String(f.id), label: f.name, icon: <CropIcon crop={f.crop} size={20} /> }))} />

      <section className={styles.group} aria-labelledby={`${id}-sens`}>
        <h2 id={`${id}-sens`} className={styles.h2}>{t('calib.howEarly')}</h2>
        <input id={`${id}-range`} type="range" min={0} max={2} step={1} value={sIndex} disabled={!online} className={styles.range}
          aria-label={t('calib.sensitivity')} aria-valuetext={t(`calib.${form.sensitivity}`)}
          onChange={(e) => setForm({ ...form, sensitivity: SENS[Number(e.target.value)] ?? 'normal' })} />
        <div className={styles.rangeLabels} aria-hidden="true">
          {SENS.map((s) => <span key={s} data-active={s === form.sensitivity || undefined}>{t(`calib.${s}`)}</span>)}
        </div>
        <p className={styles.help}>
          {hours?.[form.sensitivity] ? t('calib.leadExplain', { level: t(`calib.${form.sensitivity}`), hours: t('units.hours', { count: hours[form.sensitivity] }) }) : t('calib.leadUnknown', { level: t(`calib.${form.sensitivity}`) })}
        </p>
      </section>

      <section className={styles.group} aria-labelledby={`${id}-frost`}>
        <h2 id={`${id}-frost`} className={styles.h2}><ThermometerSnowflake size={24} aria-hidden="true" /> {t('calib.frostTitle')}</h2>
        <p className={styles.help}>{d.frost_threshold_c !== null ? t('calib.defaultValue', { crop: c, value: formatTemp(d.frost_threshold_c, locale), source: d.source }) : t('calib.noDefault')}</p>
        <div className={styles.stepRow}>
          <Stepper id={`${id}-frost-in`} label={t('calib.frostTitle')} value={form.frost} step={step} unit="°C" disabled={!online || d.frost_threshold_c === null && calibration.frost_threshold_c === null}
            onChange={(v) => setForm({ ...form, frost: v })} lowerLabel={t('calib.lower', { name: t('calib.frostTitle'), step: formatTemp(step, locale) })}
            raiseLabel={t('calib.raise', { name: t('calib.frostTitle'), step: formatTemp(step, locale) })} error={errors.frost_threshold_c} />
          {preview(form.frost, d.frost_threshold_c, 'frost')}
        </div>
        {d.frost_threshold_c !== null ? <Button variant="text" onClick={() => setForm({ ...form, frost: d.frost_threshold_c })}>{t('calib.reset')}</Button> : null}
      </section>

      <section className={styles.group} aria-labelledby={`${id}-heat`}>
        <h2 id={`${id}-heat`} className={styles.h2}><ThermometerSun size={24} aria-hidden="true" /> {t('calib.heatTitle')}</h2>
        <p className={styles.help}>{d.heat_threshold_c !== null ? t('calib.defaultValue', { crop: c, value: formatTemp(d.heat_threshold_c, locale), source: d.source }) : t('calib.noDefault')}</p>
        <div className={styles.stepRow}>
          <Stepper id={`${id}-heat-in`} label={t('calib.heatTitle')} value={form.heat} step={step} unit="°C" disabled={!online || d.heat_threshold_c === null && calibration.heat_threshold_c === null}
            onChange={(v) => setForm({ ...form, heat: v })} lowerLabel={t('calib.lower', { name: t('calib.heatTitle'), step: formatTemp(step, locale) })}
            raiseLabel={t('calib.raise', { name: t('calib.heatTitle'), step: formatTemp(step, locale) })} error={errors.heat_threshold_c} />
          {preview(form.heat, d.heat_threshold_c, 'heat')}
        </div>
        {d.heat_threshold_c !== null ? <Button variant="text" onClick={() => setForm({ ...form, heat: d.heat_threshold_c })}>{t('calib.reset')}</Button> : null}
      </section>

      <section className={styles.group} aria-labelledby={`${id}-lead`}>
        <h2 id={`${id}-lead`} className={styles.h2}>{t('calib.leadTitle')}</h2>
        <Stepper id={`${id}-lead-in`} label={t('calib.leadTitle')} value={form.lead} step={6} min={6} max={168} decimals={0} unit={t('units.hours', { count: form.lead }).replace(/^[\d,]+\s*/, '')}
          disabled={!online} onChange={(v) => setForm({ ...form, lead: v ?? 24 })} help={`${t('calib.leadHelp')} ${t('calib.leadRange')}`}
          lowerLabel={t('calib.lower', { name: t('calib.leadTitle'), step: t('units.hours', { count: 6 }) })} raiseLabel={t('calib.raise', { name: t('calib.leadTitle'), step: t('units.hours', { count: 6 }) })}
          error={errors.harvest_lead_hours} />
      </section>

      <section className={styles.group} aria-labelledby={`${id}-mandi`}>
        <h2 id={`${id}-mandi`} className={styles.h2}>{t('calib.mandiTitle')}</h2>
        <SelectField id={`${id}-mandi-in`} label={t('calib.mandiTitle')} value={form.mandi} disabled={!online} onChange={(e) => setForm({ ...form, mandi: e.target.value })} error={errors.primary_mandi}>
          <option value="">{t('calib.mandiNone')}</option>
          {mandis.map((m) => <option key={m.name} value={m.name}>{m.distance_km !== null ? t('market.mandiOption', { name: m.name, km: formatWithUnit(m.distance_km, t('units.km'), locale) }) : m.name}</option>)}
        </SelectField>
      </section>

      {errors.save ? <p className={styles.error} role="alert">{errors.save}</p> : null}
      {done && !dirty ? <Banner variant="success">{t('calib.saved')}</Banner> : null}
      <div className={styles.saveBar}>
        {dirty ? <p className={styles.unsaved}>{t('calib.unsaved')}</p> : null}
        <Button size="lg" fullWidth loading={saving} loadingLabel={t('common.saving')} disabled={!online} onClick={() => void save()}>{t('calib.save')}</Button>
      </div>
      <Dialog open={switchTo !== null} title={t('calib.switchTitle', { field: fieldName })} onCancel={() => setSwitchTo(null)}
        actions={<>
          <Button variant="secondary" onClick={() => { const f = switchTo!; setSwitchTo(null); goField(f); }}>{t('calib.discard')}</Button>
          <Button onClick={async () => { const f = switchTo!; setSwitchTo(null); if (await save()) goField(f); }}>{t('common.save')}</Button>
        </>} />
    </div>
  );
}
