import Link from 'next/link';
import type { AnchorHTMLAttributes, ButtonHTMLAttributes, ReactNode, Ref } from 'react';
import { LoaderCircle } from '@/components/Icon';
import styles from './Button.module.css';

type Variant = 'primary' | 'secondary' | 'text' | 'danger' | 'call';
type Size = 'lg' | 'md';

interface Common {
  variant?: Variant;
  size?: Size;
  icon?: ReactNode;
  iconAfter?: ReactNode;
  fullWidth?: boolean;
  children: ReactNode;
}

export function Button({
  variant = 'primary', size = 'md', icon, iconAfter, fullWidth, loading, loadingLabel, children, className, disabled, ref, ...rest
}: Common & ButtonHTMLAttributes<HTMLButtonElement> & { loading?: boolean; loadingLabel?: string; ref?: Ref<HTMLButtonElement> }) {
  return (
    <button
      ref={ref}
      type="button"
      {...rest}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={[styles.button, className ?? ''].join(' ')}
      data-variant={variant}
      data-size={size}
      data-full={fullWidth || undefined}
    >
      {loading ? <LoaderCircle size={20} aria-hidden="true" className={styles.spin} /> : icon}
      <span className={styles.label}>{loading && loadingLabel ? loadingLabel : children}</span>
      {iconAfter}
    </button>
  );
}

export function ButtonLink({
  variant = 'primary', size = 'md', icon, iconAfter, fullWidth, children, className, href, external, ...rest
}: Common & Omit<AnchorHTMLAttributes<HTMLAnchorElement>, 'href'> & { href: string; external?: boolean }) {
  const cls = [styles.button, className ?? ''].join(' ');
  const inner = (
    <>
      {icon}
      <span className={styles.label}>{children}</span>
      {iconAfter}
    </>
  );
  if (external || href.startsWith('tel:') || href.startsWith('http')) {
    return (
      <a {...rest} href={href} className={cls} data-variant={variant} data-size={size} data-full={fullWidth || undefined}
        {...(href.startsWith('http') ? { target: '_blank', rel: 'noopener noreferrer' } : {})}>
        {inner}
      </a>
    );
  }
  return (
    <Link {...rest} href={href} className={cls} data-variant={variant} data-size={size} data-full={fullWidth || undefined}>
      {inner}
    </Link>
  );
}

export function IconButton({ label, children, className, showLabel, ...rest }: ButtonHTMLAttributes<HTMLButtonElement> & { label: string; children: ReactNode; showLabel?: boolean }) {
  return (
    <button type="button" {...rest} aria-label={showLabel ? undefined : label} className={[styles.iconButton, className ?? ''].join(' ')} data-labelled={showLabel || undefined}>
      {children}
      {showLabel ? <span className={styles.iconLabel}>{label}</span> : null}
    </button>
  );
}
