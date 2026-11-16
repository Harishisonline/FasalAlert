/**
 * The app's information architecture in one place (docs/UX_QA_AUDIT.md, design.md 11):
 * which destination a path belongs to, and which shell a path renders in.
 */
export type Destination = 'home' | 'fields' | 'ask' | 'market' | 'alerts' | 'map' | 'settings';
export type ShellKind = 'app' | 'focus' | 'public';

/** Primary destinations, in nav order. Mobile shows the first five in the bottom bar; the rest live in More. */
export const PRIMARY: { key: Destination; segment: string; labelKey: string }[] = [
  { key: 'home', segment: 'home', labelKey: 'nav.home' },
  { key: 'fields', segment: 'fields', labelKey: 'nav.fields' },
  { key: 'ask', segment: 'ask', labelKey: 'nav.ask' },
  { key: 'market', segment: 'market', labelKey: 'nav.market' },
  { key: 'alerts', segment: 'alert', labelKey: 'nav.alerts' },
  { key: 'map', segment: 'map', labelKey: 'nav.map' },
];
export const MOBILE_TABS: Destination[] = ['home', 'fields', 'ask', 'market', 'alerts'];

function segments(pathname: string): string[] {
  return pathname.split('?')[0]!.split('/').filter(Boolean);
}

/** The destination a /[locale]/... path belongs to. A field's detail page belongs to My Fields. */
export function destinationFor(pathname: string): Destination | null {
  const [, first] = segments(pathname);
  switch (first) {
    case 'home':
      return 'home';
    case 'fields':
    case 'field':
      return 'fields';
    case 'ask':
      return 'ask';
    case 'market':
      return 'market';
    case 'alert':
      return 'alerts';
    case 'map':
      return 'map';
    case 'settings':
      return 'settings';
    default:
      return null;
  }
}

/**
 * Sign in, first-time onboarding, add-field and the offline fallback use a focused layout with their own
 * back and progress controls; every other page uses the app shell when signed in and the public header otherwise.
 */
export function shellFor(pathname: string, signedIn: boolean): ShellKind {
  const [, first, second] = segments(pathname);
  if (first === 'signin' || first === 'onboarding' || first === 'offline') return 'focus';
  if (first === 'fields' && second === 'new') return 'focus';
  return signedIn ? 'app' : 'public';
}
