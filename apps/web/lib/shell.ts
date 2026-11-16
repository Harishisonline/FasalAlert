import { getFields, getMe, getUnreadAlerts, hasSession } from './api';
import type { Locale } from './locales';
import { loc } from './view';
import type { ShellData } from '@/components/Nav/types';

/** Chrome data for the AppShell: user, fields (side nav, MoreDrawer) and the unread count. */
export async function loadShellData(locale: Locale): Promise<ShellData> {
  if (!(await hasSession())) return { signedIn: false, user: null, fields: [], unread: 0 };
  const [me, fields, unread] = await Promise.all([getMe(), getFields(), getUnreadAlerts()]);
  if (!me.ok && me.status === 401) return { signedIn: false, user: null, fields: [], unread: 0 };
  return {
    signedIn: true,
    user: me.ok ? { name: me.data.name, phoneMasked: me.data.phone_masked } : null,
    fields: fields.ok ? fields.data.map((f) => ({ id: f.id, name: f.name, crop: f.crop, stageLabel: f.stage?.stage_label ? loc(f.stage.stage_label, locale) : null })) : [],
    unread: unread.ok ? unread.data.unread : 0,
  };
}
