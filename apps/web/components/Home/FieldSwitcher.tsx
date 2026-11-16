'use client';
import { useRouter } from 'next/navigation';
import { useId, useTransition } from 'react';
import { useI18n } from '@/components/I18n';
import styles from './FieldSwitcher.module.css';

/** Choose which field the Home dashboard shows (?field=). A real select, so it works with any input method. */
export function FieldSwitcher({ fields, value }: { fields: { id: number; name: string }[]; value: number }) {
  const { t, locale } = useI18n();
  const router = useRouter();
  const id = useId();
  const [pending, start] = useTransition();
  return (
    <div className={styles.switcher} aria-busy={pending || undefined}>
      <label htmlFor={id} className={styles.label}>{t('home.showing')}</label>
      <select id={id} className={styles.select} value={value}
        onChange={(e) => start(() => router.push(`/${locale}/home?field=${e.target.value}`, { scroll: false }))}>
        {fields.map((f) => <option key={f.id} value={f.id}>{f.name}</option>)}
      </select>
    </div>
  );
}
