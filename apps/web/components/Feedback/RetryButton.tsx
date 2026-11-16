'use client';
import { useRouter } from 'next/navigation';
import { useTransition } from 'react';
import { useT } from '@/components/I18n';
import { Button } from '@/components/UI/Button';

/** Re-render the server data for this page (RouteError "Try again"). */
export function RetryButton({ variant = 'secondary' }: { variant?: 'primary' | 'secondary' }) {
  const t = useT();
  const router = useRouter();
  const [pending, start] = useTransition();
  return (
    <Button variant={variant} loading={pending} loadingLabel={t('common.tryingAgain')} onClick={() => start(() => router.refresh())}>
      {t('common.tryAgain')}
    </Button>
  );
}
