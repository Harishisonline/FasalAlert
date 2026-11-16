'use client';
import { useRef, type KeyboardEvent, type ReactNode } from 'react';
import { Check } from '@/components/Icon';
import styles from './Chips.module.css';

/** A filter chip: a toggle button with aria-pressed (design.md A.6). */
export function FilterChip({ pressed, onClick, icon, children }: { pressed: boolean; onClick: () => void; icon?: ReactNode; children: ReactNode }) {
  return (
    <button type="button" className={styles.chip} aria-pressed={pressed} onClick={onClick}>
      {pressed ? <Check size={20} aria-hidden="true" /> : icon}
      <span className={styles.text}>{children}</span>
    </button>
  );
}

export interface ChipOption { value: string; label: string; icon?: ReactNode }

/** Single-select chips with radio semantics and arrow keys (field selectors, design.md 12.7 a11y). */
export function ChipRadioGroup({ label, options, value, onChange, className }: { label: string; options: ChipOption[]; value: string; onChange: (v: string) => void; className?: string }) {
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  const onKey = (e: KeyboardEvent, i: number) => {
    const n = options.length;
    let next = -1;
    if (e.key === 'ArrowRight' || e.key === 'ArrowDown') next = (i + 1) % n;
    if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') next = (i - 1 + n) % n;
    if (e.key === 'Home') next = 0;
    if (e.key === 'End') next = n - 1;
    if (next >= 0) {
      e.preventDefault();
      refs.current[next]?.focus();
      onChange(options[next]!.value);
    }
  };
  return (
    <div role="radiogroup" aria-label={label} className={[styles.group, className ?? ''].join(' ')}>
      {options.map((o, i) => {
        const checked = o.value === value;
        return (
          <button
            key={o.value}
            ref={(el) => { refs.current[i] = el; }}
            type="button"
            role="radio"
            aria-checked={checked}
            tabIndex={checked || (!options.some((x) => x.value === value) && i === 0) ? 0 : -1}
            className={styles.chip}
            onClick={() => onChange(o.value)}
            onKeyDown={(e) => onKey(e, i)}
            title={o.label}
          >
            {checked ? <Check size={20} aria-hidden="true" /> : o.icon}
            <span className={styles.text} data-truncate>{o.label}</span>
          </button>
        );
      })}
    </div>
  );
}

/** Segmented control for local options (design.md A.7). Never for navigation. */
export function Segmented({ label, options, value, onChange, disabled, name }: { label: string; options: { value: string; label: string; lang?: string }[]; value: string; onChange: (v: string) => void; disabled?: boolean; name?: string }) {
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  const onKey = (e: KeyboardEvent, i: number) => {
    const n = options.length;
    let next = -1;
    if (e.key === 'ArrowRight' || e.key === 'ArrowDown') next = (i + 1) % n;
    if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') next = (i - 1 + n) % n;
    if (next >= 0) {
      e.preventDefault();
      refs.current[next]?.focus();
      onChange(options[next]!.value);
    }
  };
  return (
    <div role="radiogroup" aria-label={label} className={styles.segmented} data-name={name}>
      {options.map((o, i) => (
        <button
          key={o.value}
          ref={(el) => { refs.current[i] = el; }}
          type="button"
          role="radio"
          lang={o.lang}
          aria-checked={o.value === value}
          tabIndex={o.value === value ? 0 : -1}
          disabled={disabled}
          className={styles.segment}
          onClick={() => onChange(o.value)}
          onKeyDown={(e) => onKey(e, i)}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}
