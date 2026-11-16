'use client';
import { useRef, type ReactNode } from 'react';
import { useLatest } from '@/lib/hooks';
import { Minus, Plus } from '@/components/Icon';
import { FieldMessage, describedBy } from './Field';
import styles from './Stepper.module.css';

/** A minus button, a number input and a plus button, each 48px (design.md A.9). */
export function Stepper({ id, label, value, onChange, step, min, max, unit, lowerLabel, raiseLabel, help, error, disabled, decimals = 1 }: {
  id: string; label: ReactNode; value: number | null; onChange: (v: number | null) => void; step: number; min?: number; max?: number;
  unit?: string; lowerLabel: string; raiseLabel: string; help?: ReactNode; error?: ReactNode; disabled?: boolean; decimals?: number;
}) {
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);
  const valueRef = useLatest(value);
  const clamp = (v: number) => {
    let x = Math.round(v / step) * step;
    if (min !== undefined) x = Math.max(min, x);
    if (max !== undefined) x = Math.min(max, x);
    return Number(x.toFixed(decimals));
  };
  const bump = (dir: 1 | -1) => {
    const base = valueRef.current ?? min ?? 0;
    const next = clamp(base + dir * step);
    valueRef.current = next;
    onChange(next);
  };
  const startRepeat = (dir: 1 | -1) => {
    stopRepeat();
    timer.current = setInterval(() => bump(dir), 250); // long press repeats at 4 steps per second
  };
  const stopRepeat = () => {
    if (timer.current) clearInterval(timer.current);
    timer.current = null;
  };
  const atMin = value !== null && min !== undefined && value <= min;
  const atMax = value !== null && max !== undefined && value >= max;
  return (
    <div className={styles.field}>
      <label htmlFor={id} className={styles.label}>{label}</label>
      <div className={styles.row}>
        <button type="button" className={styles.btn} aria-label={lowerLabel} disabled={disabled || atMin}
          onClick={() => bump(-1)} onPointerDown={() => { timer.current = setTimeout(() => startRepeat(-1), 400) as unknown as ReturnType<typeof setInterval>; }}
          onPointerUp={stopRepeat} onPointerLeave={stopRepeat}>
          <Minus size={24} aria-hidden="true" />
        </button>
        <div className={styles.control} data-invalid={error ? true : undefined}>
          <input
            id={id}
            type="number"
            inputMode="decimal"
            step={step}
            min={min}
            max={max}
            disabled={disabled}
            value={value === null ? '' : value}
            onChange={(e) => onChange(e.target.value === '' ? null : Number(e.target.value))}
            aria-invalid={error ? true : undefined}
            aria-describedby={describedBy(id, help, error)}
            className={styles.input}
          />
          {unit ? <span className={styles.unit}>{unit}</span> : null}
        </div>
        <button type="button" className={styles.btn} aria-label={raiseLabel} disabled={disabled || atMax}
          onClick={() => bump(1)} onPointerDown={() => { timer.current = setTimeout(() => startRepeat(1), 400) as unknown as ReturnType<typeof setInterval>; }}
          onPointerUp={stopRepeat} onPointerLeave={stopRepeat}>
          <Plus size={24} aria-hidden="true" />
        </button>
      </div>
      <FieldMessage id={id} help={help} error={error} />
    </div>
  );
}
