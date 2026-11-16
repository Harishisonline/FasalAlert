'use client';
import { useId, useMemo, useState } from 'react';
import { Check, ChevronDown, Search } from '@/components/Icon';
import { Sheet } from './Sheet';
import styles from './SearchSheet.module.css';

export interface SearchOption { value: string; label: string; search: string }

/** Long lists (more than 15 options): a select-looking button opening a searchable sheet (design.md A.3). */
export function SearchSheet({ id, label, placeholder, value, options, onChange, searchLabel, emptyLabel, closeLabel, expandLabel, collapseLabel, disabled }: {
  id: string; label: string; placeholder: string; value: string; options: SearchOption[]; onChange: (v: string) => void;
  searchLabel: string; emptyLabel: string; closeLabel: string; expandLabel: string; collapseLabel: string; disabled?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState('');
  const sid = useId();
  const current = options.find((o) => o.value === value);
  const shown = useMemo(() => {
    const needle = q.trim().toLocaleLowerCase();
    return needle ? options.filter((o) => o.search.includes(needle)) : options;
  }, [q, options]);
  return (
    <div className={styles.field}>
      <span id={`${id}-label`} className={styles.label}>{label}</span>
      <button type="button" id={id} className={styles.trigger} aria-haspopup="dialog" aria-labelledby={`${id}-label ${id}`} disabled={disabled} onClick={() => setOpen(true)}>
        <span className={styles.value} data-placeholder={!current || undefined}>{current?.label ?? placeholder}</span>
        <ChevronDown size={24} aria-hidden="true" />
      </button>
      <Sheet open={open} onClose={() => setOpen(false)} title={label} closeLabel={closeLabel} expandLabel={expandLabel} collapseLabel={collapseLabel} initial="full">
        <div className={styles.search}>
          <Search size={20} aria-hidden="true" />
          <label htmlFor={`${sid}-q`} className="visually-hidden">{searchLabel}</label>
          <input id={`${sid}-q`} className={styles.input} value={q} onChange={(e) => setQ(e.target.value)} placeholder={searchLabel} autoComplete="off" />
        </div>
        {shown.length === 0 ? <p className={styles.empty}>{emptyLabel}</p> : (
          <ul className={styles.list} role="listbox" aria-label={label}>
            {shown.map((o) => (
              <li key={o.value} role="option" aria-selected={o.value === value}>
                <button type="button" className={styles.row} onClick={() => { onChange(o.value); setOpen(false); setQ(''); document.getElementById(id)?.focus(); }}>
                  <span>{o.label}</span>
                  {o.value === value ? <Check size={20} aria-hidden="true" /> : null}
                </button>
              </li>
            ))}
          </ul>
        )}
      </Sheet>
    </div>
  );
}
