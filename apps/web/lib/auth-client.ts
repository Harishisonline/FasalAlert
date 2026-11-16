'use client';
import { clearDeviceData } from './offline';

/** Sign out: clear the httpOnly session cookies on the server, wipe device data, go to R2 (PRD §7.9). */
export async function signOut(locale: string): Promise<void> {
  try {
    await fetch('/api/auth/signout', { method: 'POST', credentials: 'same-origin' });
  } finally {
    await clearDeviceData();
    // eslint-disable-next-line @next/next/no-location-assign-relative-destination -- a full load clears the session-aware layout
    window.location.assign(`/${locale}/signin`);
  }
}
