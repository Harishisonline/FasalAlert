import type { ReactNode } from 'react';
import { CircleAlert, CircleCheck, CloudOff, Info, TriangleAlert, WifiOff } from '@/components/Icon';
import styles from './Banner.module.css';

type Variant = 'danger' | 'warning' | 'info' | 'success';
const ICONS = { danger: CircleAlert, warning: TriangleAlert, info: Info, success: CircleCheck, 'cloud-off': CloudOff, 'wifi-off': WifiOff } as const;

/** Page-level banner (design.md A.10). Never auto-dismissed. At most one per page. */
export function Banner({ variant, icon, children, action }: { variant: Variant; icon?: keyof typeof ICONS; children: ReactNode; action?: ReactNode }) {
  const Icon = ICONS[icon ?? variant];
  return (
    <div className={styles.banner} data-variant={variant} role={variant === 'danger' ? 'alert' : 'status'}>
      <Icon size={24} aria-hidden="true" className={styles.icon} />
      <div className={styles.text}>{children}</div>
      {action ? <div className={styles.action}>{action}</div> : null}
    </div>
  );
}
