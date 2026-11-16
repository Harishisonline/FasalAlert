import { MapPinOff } from '@/components/Icon';
import { EmptyState } from '@/components/Feedback/EmptyState';
import { PageMain } from '@/components/Layout/Page';
import { ButtonLink } from '@/components/UI/Button';
import type { Translator } from '@/lib/i18n';
import type { Locale } from '@/lib/locales';
import { FocusOnMount } from './FocusOnMount';

/**
 * R12 "This page does not exist" in the current locale with a link to Home (PRD §7.11). It never
 * says a field belongs to someone else (PRD §7.4). Signed out, Home sends the user to R2 (fix 7).
 */
export function NotFoundView({ t, locale, signedIn }: { t: Translator; locale: Locale; signedIn: boolean }) {
  return (
    <>
      <PageMain width="narrow">
        <EmptyState variant="page" icon={<MapPinOff size={48} aria-hidden="true" />} title={t('notFound.title')} body={t('notFound.body')} headingLevel={1} headingId="nf-title"
          action={<ButtonLink href={signedIn ? `/${locale}/home` : `/?lang=${locale}`} size="lg" fullWidth>{signedIn ? t('notFound.goHome') : t('notFound.goLanding')}</ButtonLink>} />
        <FocusOnMount targetId="nf-title" title={`${t('meta.notFoundTitle')} · FasalAlert`} />
      </PageMain>
    </>
  );
}
