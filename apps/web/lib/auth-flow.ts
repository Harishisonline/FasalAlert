/** Where a user goes after signing in (docs/UX_QA_AUDIT.md FLOW-02). Pure, so it is unit tested. */
import { LOCALES, type Locale } from './locales';
import { safeNext } from './phone';

/** Paths that make no sense as a post-sign-in destination (they would loop or repeat first-time setup). */
function isEntryPath(path: string): boolean {
  const [first, second] = path.split('?')[0]!.split('/').filter(Boolean);
  if (!first) return true; // the landing page
  if ((LOCALES as readonly string[]).includes(first)) return second === undefined || second === 'signin' || second === 'onboarding';
  return false;
}

/**
 * A first-time user (no fields yet) always goes to onboarding, whatever ?next= says: every other page needs a
 * field. A returning user goes to a safe ?next= if there is one, otherwise Home. Onboarding is never repeated.
 */
export function postSignInTarget({ hasFields, next, locale }: { hasFields: boolean; next: string | null; locale: Locale }): string {
  if (!hasFields) return `/${locale}/onboarding`;
  const safe = safeNext(next);
  if (safe && !isEntryPath(safe)) return safe;
  return `/${locale}/home`;
}
