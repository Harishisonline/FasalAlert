import { headers } from 'next/headers';
import { LoadingRegion, Skeleton } from '@/components/Feedback/Skeleton';
import { createTranslator } from '@/lib/i18n';
import { DEFAULT_LOCALE, isLocale } from '@/lib/locales';
import styles from './Chat.module.css';

function Conversation() {
  return (
    <div className={styles.workspace}>
      <div className={styles.head}><Skeleton height={20} width="40%" /></div>
      <div className={styles.scroll}>
        <div className={styles.thread}>
          <div className={styles.userRow}><Skeleton height={44} width="55%" radius="md" /></div>
          <div className={styles.skeletonAi}><Skeleton height={16} width="90%" /><Skeleton height={16} width="75%" /><Skeleton height={96} radius="md" /></div>
          <div className={styles.userRow}><Skeleton height={44} width="40%" radius="md" /></div>
        </div>
      </div>
      <div className={styles.composerWrap}><Skeleton height={104} radius="md" /></div>
    </div>
  );
}

/**
 * Loading state for Ask. Inside the Ask frame it is only the conversation (the frame and its main landmark stay);
 * while the frame itself loads it is the whole frame.
 */
export async function ChatSkeleton({ frame = false }: { frame?: boolean }) {
  const raw = (await headers()).get('x-fa-locale');
  const t = createTranslator(isLocale(raw) ? raw : DEFAULT_LOCALE);
  if (!frame) {
    return <LoadingRegion label={t('state.loading')} className={styles.workspace}><Conversation /></LoadingRegion>;
  }
  return (
    <div className={styles.frame}>
      <div className={styles.side} aria-hidden="true">
        <div className={styles.skeletonSide}>
          <Skeleton height={44} radius="md" /><Skeleton height={44} radius="md" />
          {[0, 1, 2, 3, 4, 5].map((i) => <Skeleton key={i} height={36} radius="md" />)}
        </div>
      </div>
      <main id="main" tabIndex={-1} className={styles.main}>
        <LoadingRegion label={t('state.loading')} className={styles.workspace}><Conversation /></LoadingRegion>
      </main>
    </div>
  );
}
