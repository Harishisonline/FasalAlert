'use client';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import { useT } from '@/components/I18n';
import { Segmented } from '@/components/UI/Chips';
import styles from './RangeToggle.module.css';

/** 30 or 90 days of history, shown at 480px and up (design.md 15.5). */
export function RangeToggle({ days }: { days: 30 | 90 }) {
  const t = useT();
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  return (
    <div className={styles.wrap}>
      <Segmented
        label={t('market.price.rangeLabel')}
        value={String(days)}
        options={[{ value: '30', label: t('market.price.range30') }, { value: '90', label: t('market.price.range90') }]}
        onChange={(v) => {
          const next = new URLSearchParams(params.toString());
          next.set('range', v);
          router.replace(`${pathname}?${next.toString()}`, { scroll: false });
        }}
      />
    </div>
  );
}
