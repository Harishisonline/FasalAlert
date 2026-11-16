import { headers } from 'next/headers';
import { PageMain } from '@/components/Layout/Page';
import { createTranslator } from '@/lib/i18n';
import { DEFAULT_LOCALE, isLocale } from '@/lib/locales';
import { LoadingRegion, Skeleton } from './Skeleton';
import styles from './PageSkeleton.module.css';

/** Route loading state (the loading.tsx files under app/[locale]): the page shape while its server data loads. */
export async function PageSkeleton({ layout = 'list', width = 'max' }: { layout?: 'dashboard' | 'list' | 'detail' | 'form' | 'map'; width?: 'max' | 'reading' }) {
  const raw = (await headers()).get('x-fa-locale');
  const t = createTranslator(isLocale(raw) ? raw : DEFAULT_LOCALE);
  return (
    <PageMain width={width}>
      <LoadingRegion label={t('state.loading')} className={styles.wrap}>
        <div className={styles.head}><Skeleton height={14} width="30%" /><Skeleton height={30} width="55%" /><Skeleton height={16} width="70%" /></div>
        {layout === 'dashboard' ? (
          <div className={styles.dashboard}><div className={styles.col}><Skeleton height={260} radius="md" /><Skeleton height={160} radius="md" /></div><div className={styles.col}><Skeleton height={180} radius="md" /><Skeleton height={140} radius="md" /><Skeleton height={120} radius="md" /></div></div>
        ) : layout === 'map' ? (
          <div className={styles.dashboard}><Skeleton height={420} radius="md" /><div className={styles.col}><Skeleton height={48} radius="md" />{[0, 1, 2, 3, 4].map((i) => <Skeleton key={i} height={64} radius="md" />)}</div></div>
        ) : layout === 'detail' ? (
          <div className={styles.col}><Skeleton height={220} radius="md" /><Skeleton height={120} radius="md" /><Skeleton height={180} radius="md" /></div>
        ) : layout === 'form' ? (
          <div className={styles.col}>{[0, 1, 2, 3].map((i) => <Skeleton key={i} height={72} radius="md" />)}</div>
        ) : (
          <div className={styles.grid}>{[0, 1, 2, 3, 4, 5].map((i) => <Skeleton key={i} height={200} radius="md" />)}</div>
        )}
      </LoadingRegion>
    </PageMain>
  );
}
