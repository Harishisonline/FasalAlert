import type { Metadata } from 'next';
import { redirect } from 'next/navigation';
import { SignInFlow } from '@/components/Auth/SignInFlow';
import { getFields, getMe, hasSession } from '@/lib/api';
import { postSignInTarget } from '@/lib/auth-flow';
import { createTranslator } from '@/lib/i18n';
import { isLocale, type Locale } from '@/lib/locales';
import { safeNext } from '@/lib/phone';

export async function generateMetadata({ params }: { params: Promise<{ locale: string }> }): Promise<Metadata> {
  const { locale } = await params;
  return { title: createTranslator(isLocale(locale) ? locale : 'mr')('signin.title') };
}

/**
 * R2 Sign in or create an account (PRD §7.2) in a focused layout. Someone already signed in goes where a
 * fresh sign-in would take them: onboarding without fields, otherwise ?next= or Home (lib/auth-flow.ts).
 */
export default async function SignInPage({ params, searchParams }: { params: Promise<{ locale: string }>; searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const locale = (await params).locale as Locale;
  const sp = await searchParams;
  const next = safeNext(typeof sp.next === 'string' ? sp.next : null);
  if (await hasSession()) {
    const [me, fields] = await Promise.all([getMe(), getFields()]);
    if (me.ok) redirect(postSignInTarget({ hasFields: fields.ok ? fields.data.length > 0 : true, next, locale }));
  }
  return <SignInFlow next={next} expired={sp.reason === 'expired'} />;
}
