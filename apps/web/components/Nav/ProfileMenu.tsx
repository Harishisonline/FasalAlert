'use client';
import Link from 'next/link';
import { useEffect, useRef, useState, type KeyboardEvent } from 'react';
import { ChevronDown, LogOut, Settings, SlidersHorizontal } from '@/components/Icon';
import { useI18n } from '@/components/I18n';
import { signOut } from '@/lib/auth-client';
import styles from './ProfileMenu.module.css';

/** Desktop profile menu: a popover anchored at the bottom of the side nav (design.md 11.5). */
export function ProfileMenu({ name, phoneMasked }: { name: string | null; phoneMasked: string }) {
  const { t, locale } = useI18n();
  const [open, setOpen] = useState(false);
  const wrap = useRef<HTMLDivElement>(null);
  const btn = useRef<HTMLButtonElement>(null);
  const items = useRef<(HTMLElement | null)[]>([]);
  useEffect(() => {
    if (!open) return;
    items.current[0]?.focus();
    const onDoc = (e: PointerEvent) => { if (!wrap.current?.contains(e.target as Node)) setOpen(false); };
    document.addEventListener('pointerdown', onDoc);
    return () => document.removeEventListener('pointerdown', onDoc);
  }, [open]);
  const onKey = (e: KeyboardEvent) => {
    const list = items.current.filter(Boolean) as HTMLElement[];
    const i = list.indexOf(document.activeElement as HTMLElement);
    if (e.key === 'Escape') { setOpen(false); btn.current?.focus(); }
    if (e.key === 'ArrowDown') { e.preventDefault(); list[(i + 1) % list.length]?.focus(); }
    if (e.key === 'ArrowUp') { e.preventDefault(); list[(i - 1 + list.length) % list.length]?.focus(); }
  };
  const initial = (name ?? '').trim().charAt(0) || '·';
  return (
    <div ref={wrap} className={styles.wrap} onKeyDown={onKey}>
      {open ? (
        <ul className={styles.menu} role="menu" aria-label={t('nav.profileMenu')}>
          <li role="none"><Link role="menuitem" ref={(el) => { items.current[0] = el; }} href={`/${locale}/settings`} className={styles.item} onClick={() => setOpen(false)}><Settings size={24} aria-hidden="true" />{t('nav.settings')}</Link></li>
          <li role="none"><Link role="menuitem" ref={(el) => { items.current[1] = el; }} href={`/${locale}/settings/calibration`} className={styles.item} onClick={() => setOpen(false)}><SlidersHorizontal size={24} aria-hidden="true" />{t('nav.calibration')}</Link></li>
          <li role="none"><button role="menuitem" ref={(el) => { items.current[2] = el; }} type="button" className={styles.item} data-danger onClick={() => void signOut(locale)}><LogOut size={24} aria-hidden="true" />{t('nav.signOut')}</button></li>
        </ul>
      ) : null}
      <button ref={btn} type="button" className={styles.trigger} aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen(!open)}>
        <span className={styles.avatar} aria-hidden="true">{initial}</span>
        <span className={styles.who}>
          {name ? <span className={styles.name}>{name}</span> : null}
          <span className={styles.phone}>{phoneMasked}</span>
        </span>
        <ChevronDown size={20} aria-hidden="true" />
        <span className="visually-hidden">{t('nav.profileMenu')}</span>
      </button>
    </div>
  );
}
