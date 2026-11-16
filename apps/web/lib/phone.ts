/** Phone and redirect helpers shared by R2 (client) and its server page. */

/** Paste is normalised: strips +91, a leading 0, spaces and dashes (design.md 12.2). */
export function normalisePhone(raw: string): string {
  let d = raw.replace(/[^\d+]/g, '');
  if (d.startsWith('+91')) d = d.slice(3);
  else if (d.startsWith('91') && d.length > 10) d = d.slice(2);
  d = d.replace(/\D/g, '');
  if (d.startsWith('0')) d = d.replace(/^0+/, '');
  return d.slice(0, 10);
}

/** Exactly 10 digits, first digit 6 to 9. */
export function isValidPhone(d: string): boolean {
  return /^[6-9]\d{9}$/.test(d);
}

/** Only same-origin paths are accepted for ?next= (no open redirects). */
export function safeNext(next: string | null | undefined): string | null {
  if (!next || !next.startsWith('/') || next.startsWith('//') || next.includes('\\')) return null;
  return next;
}
