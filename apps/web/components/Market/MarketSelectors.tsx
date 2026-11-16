'use client';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import { useId, useTransition } from 'react';
import type { Crop } from '@fasalalert/shared/api';
import { CropIcon } from '@/components/Icon';
import { useI18n } from '@/components/I18n';
import { ChipRadioGroup } from '@/components/UI/Chips';
import { SelectField } from '@/components/UI/Field';
import { formatWithUnit } from '@/lib/format';
import styles from './MarketSelectors.module.css';

/** Field chips (radio group) and the mandi select sorted by distance (PRD §7.7, design.md 12.7). */
export function MarketSelectors({ fields, fieldId, mandis, mandi }: {
  fields: { id: number; name: string; crop: Crop }[]; fieldId: number; mandis: { name: string; distance_km: number | null }[]; mandi: string | null;
}) {
  const { t, locale } = useI18n();
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const id = useId();
  const [pending, start] = useTransition();
  const go = (patch: Record<string, string | null>) => {
    const q = new URLSearchParams(params.toString());
    for (const [k, v] of Object.entries(patch)) { if (v === null) q.delete(k); else q.set(k, v); }
    start(() => router.push(`${pathname}?${q.toString()}`, { scroll: false }));
  };
  return (
    <div className={styles.selectors} aria-busy={pending || undefined}>
      <ChipRadioGroup label={t('market.fieldLabel')} value={String(fieldId)} onChange={(v) => go({ field_id: v, mandi: null })}
        options={fields.map((f) => ({ value: String(f.id), label: f.name, icon: <CropIcon crop={f.crop} size={20} /> }))} />
      {mandis.length ? (
        <SelectField id={`${id}-mandi`} label={t('market.mandiLabel')} value={mandi ?? ''} onChange={(e) => go({ mandi: e.target.value })} className={styles.mandi}>
          {mandis.map((m) => (
            <option key={m.name} value={m.name}>
              {m.distance_km !== null ? t('market.mandiOption', { name: m.name, km: formatWithUnit(m.distance_km, t('units.km'), locale) }) : m.name}
            </option>
          ))}
        </SelectField>
      ) : null}
    </div>
  );
}
