import type { ReactNode } from 'react';
import type { Crop } from '@fasalalert/shared/api';
import styles from './CropIcon.module.css';

/**
 * Semi-abstract crop drawings on Lucide's 24px grid, 2px stroke, round caps and joins
 * (design.md 9.3). Drawn by hand: no generated imagery. The crop name is always written next to it.
 */
interface Props { crop: Crop; size?: number; duotone?: boolean; className?: string }

export function CropIcon({ crop, size = 24, duotone = false, className }: Props) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      className={[styles.icon, duotone ? styles.duotone : '', className ?? ''].join(' ')}
      data-crop={crop}
    >
      {DRAWINGS[crop]}
    </svg>
  );
}

const DRAWINGS: Record<Crop, ReactNode> = {
  mango: (
    <>
      <path className={styles.fillA} d="M7.2 10.6c2.3-2.7 6.9-3 10-.4 3.1 2.6 4 6.9 1.8 9.6-2.2 2.7-6.3 2.4-8.9.4-1.6-1.2-2.3-2.7-3.5-3.7-1.4-1.2-1.5-3.8.6-5.9z" />
      <path d="M10.4 9.4 9.7 6.4" />
      <path className={styles.fillB} d="M9.7 6.4c1-2.7 3.7-4 6.9-3.5-1 2.6-3.6 3.8-6.9 3.5z" />
    </>
  ),
  pomegranate: (
    <>
      <circle className={styles.fillDanger} cx="12" cy="14.5" r="6.8" />
      <path d="M9.2 8.4 8.6 5.2l2 1.6L12 4.6l1.4 2.2 2-1.6-.6 3.2" />
      <path d="M10 14.5c.6 1.4 1.8 2.2 3.4 2.2" />
    </>
  ),
  grape: (
    <>
      <g className={styles.fillInfo}>
        <circle cx="8" cy="9.5" r="2" />
        <circle cx="12" cy="9.5" r="2" />
        <circle cx="16" cy="9.5" r="2" />
        <circle cx="10" cy="13.3" r="2" />
        <circle cx="14" cy="13.3" r="2" />
        <circle cx="12" cy="17.1" r="2" />
        <circle cx="12" cy="20.6" r="1.4" />
      </g>
      <path d="M12 7.5V3" />
      <path className={styles.fillB} d="M12 4.2c1.8-1.7 4.4-1.8 6.3-.4-1.6 1.9-4.2 2.3-6.3.4z" />
    </>
  ),
  cotton: (
    <>
      <g className={styles.fillWhite}>
        <circle cx="9" cy="8.5" r="3.2" />
        <circle cx="15" cy="8.5" r="3.2" />
        <circle cx="8.6" cy="13.8" r="3.2" />
        <circle cx="15.4" cy="13.8" r="3.2" />
      </g>
      <path className={styles.fillB} d="M7 17.6c1.6 1.8 3 2.6 5 2.6s3.4-.8 5-2.6" />
      <path d="M12 20.2V22" />
      <path d="M9.4 18.8 8 21.4M14.6 18.8 16 21.4" />
    </>
  ),
  soybean: (
    <>
      <path className={styles.fillB} d="M6.2 18.6C4.4 16.9 5 13 7.6 10.2 10.4 7.2 14.5 5 17.6 5.6c1.6.3 2 2 .9 3.6-1 1.5-3 2.4-4.2 3.9-1.3 1.6-1.7 3.8-3.6 5.3-1.6 1.2-3.4 1.2-4.5.2z" />
      <circle cx="9" cy="15.2" r="1.2" />
      <circle cx="12" cy="12" r="1.2" />
      <circle cx="15.2" cy="8.8" r="1.2" />
      <path d="M17.6 5.6c.8-1.5 2-2.4 3.4-2.6" />
    </>
  ),
  sugarcane: (
    <>
      <g className={styles.fillB}>
        <rect x="7.6" y="6" width="3" height="16" rx="1.5" />
        <rect x="13.4" y="9" width="3" height="13" rx="1.5" />
      </g>
      <path d="M7.6 11h3M7.6 16h3M13.4 14h3M13.4 18.5h3" />
      <path d="M9.1 6C8.6 3.6 10.6 2 14 2.4" />
      <path d="M14.9 9c1.1-2.8 3.8-4.2 7.1-3.7" />
    </>
  ),
};
