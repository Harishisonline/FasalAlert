'use client';
import { useRef, type KeyboardEvent } from 'react';
import type { Crop } from '@fasalalert/shared/api';
import { Check, CropIcon } from '@/components/Icon';
import { useT } from '@/components/I18n';
import styles from './CropPicker.module.css';

const CROPS: Crop[] = ['mango', 'pomegranate', 'grape', 'cotton', 'soybean', 'sugarcane'];

/** 2 x 3 grid of crop tiles with radio semantics and arrow keys (PRD §7.8, design.md 12.8). */
export function CropPicker({ value, onChange, label }: { value: Crop | null; onChange: (c: Crop) => void; label: string }) {
  const t = useT();
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  const onKey = (e: KeyboardEvent, i: number) => {
    const map: Record<string, number> = { ArrowRight: 1, ArrowDown: 2, ArrowLeft: -1, ArrowUp: -2 };
    const d = map[e.key];
    if (d === undefined) return;
    e.preventDefault();
    const next = (i + d + CROPS.length) % CROPS.length;
    refs.current[next]?.focus();
    onChange(CROPS[next]!);
  };
  return (
    <div role="radiogroup" aria-label={label} className={styles.grid}>
      {CROPS.map((c, i) => {
        const checked = value === c;
        return (
          <button key={c} ref={(el) => { refs.current[i] = el; }} type="button" role="radio" aria-checked={checked}
            tabIndex={checked || (!value && i === 0) ? 0 : -1} className={styles.tile} onClick={() => onChange(c)} onKeyDown={(e) => onKey(e, i)}>
            {checked ? <span className={styles.check} aria-hidden="true"><Check size={16} /></span> : null}
            <CropIcon crop={c} size={40} duotone />
            <span className={styles.name}>{t(`crop.${c}`)}</span>
            <span className={styles.hint}>{t(`crop.hint.${c}`)}</span>
          </button>
        );
      })}
    </div>
  );
}
