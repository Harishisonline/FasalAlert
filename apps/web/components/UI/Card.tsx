import type { HTMLAttributes, ReactNode } from 'react';
import type { DisplayLevel } from '@/lib/risk';
import styles from './Card.module.css';

export type CardVariant = 'plain' | 'risk' | 'stale' | 'abstain' | 'raw' | 'info';

/** Cards (design.md A.4). Variants are data attributes styled with attribute selectors (design.md 22.1). */
export function Card({ variant = 'plain', level, pinned, as: Tag = 'div', children, className, ...rest }: {
  variant?: CardVariant; level?: DisplayLevel; pinned?: boolean; as?: 'div' | 'article' | 'section' | 'li'; children: ReactNode;
} & HTMLAttributes<HTMLElement>) {
  return (
    <Tag {...rest} className={[styles.card, className ?? ''].join(' ')} data-variant={variant} data-level={level} data-pinned={pinned || undefined}>
      {children}
    </Tag>
  );
}
