'use client';
import { useEffect, useMemo, useRef, useState, type KeyboardEvent, type ReactNode } from 'react';
import { ChevronDown, CircleAlert } from '@/components/Icon';
import { describedBy } from './Field';
import fieldStyles from './Field.module.css';
import styles from './Combobox.module.css';

export interface ComboOption { value: string; label: string; hint?: string; search: string }

const MAX_SHOWN = 60;

/**
 * A searchable select (ARIA 1.2 combobox with a listbox popup) for long lists such as villages
 * (docs/UX_QA_AUDIT.md ONB-02). Type to filter in any of the three languages, arrow keys to move,
 * Enter to choose, Escape to close. The chosen value is shown when the input is not being edited.
 */
export function Combobox({ id, label, value, options, onChange, placeholder, disabled, emptyLabel, moreLabel, help, error, toggleLabel }: {
  id: string; label: ReactNode; value: string; options: ComboOption[]; onChange: (value: string) => void; placeholder?: string; disabled?: boolean;
  emptyLabel: string; moreLabel: (count: number) => string; help?: ReactNode; error?: ReactNode; toggleLabel: string;
}) {
  const input = useRef<HTMLInputElement>(null);
  const [text, setText] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const selected = options.find((o) => o.value === value) ?? null;
  const q = (text ?? '').normalize('NFC').toLocaleLowerCase().trim();
  const matches = useMemo(() => (q ? options.filter((o) => o.search.includes(q)) : options), [options, q]);
  const shown = matches.slice(0, MAX_SHOWN);
  const listId = `${id}-list`;

  useEffect(() => {
    if (!open) return;
    document.getElementById(`${id}-o-${active}`)?.scrollIntoView?.({ block: 'nearest' });
  }, [active, open, id]);

  const close = () => { setOpen(false); setText(null); };
  const choose = (o: ComboOption) => { onChange(o.value); close(); };
  const openList = () => {
    if (disabled) return;
    const i = selected ? Math.max(0, options.indexOf(selected)) : 0;
    setActive(q ? 0 : Math.min(i, MAX_SHOWN - 1));
    setOpen(true);
  };

  const onKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'ArrowDown') { e.preventDefault(); if (!open) openList(); else setActive((a) => Math.min(a + 1, shown.length - 1)); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); if (open) setActive((a) => Math.max(a - 1, 0)); }
    else if (e.key === 'Home' && open) { e.preventDefault(); setActive(0); }
    else if (e.key === 'End' && open) { e.preventDefault(); setActive(shown.length - 1); }
    else if (e.key === 'Enter') { if (open && shown[active]) { e.preventDefault(); choose(shown[active]!); } }
    else if (e.key === 'Escape') { if (open || text !== null) { e.preventDefault(); close(); } }
    else if (e.key === 'Tab') { if (open && q && shown.length === 1) choose(shown[0]!); else close(); }
  };

  return (
    <div className={[fieldStyles.field, styles.combo].join(' ')}>
      <label htmlFor={id} className={fieldStyles.label}>{label}</label>
      <div className={styles.anchor}>
      <div className={fieldStyles.control} data-size="lg" data-invalid={error ? true : undefined} data-disabled={disabled || undefined}>
        <input
          ref={input}
          id={id}
          type="text"
          role="combobox"
          className={fieldStyles.input}
          value={text ?? selected?.label ?? ''}
          placeholder={placeholder}
          disabled={disabled}
          autoComplete="off"
          spellCheck={false}
          aria-expanded={open}
          aria-controls={listId}
          aria-autocomplete="list"
          aria-activedescendant={open && shown[active] ? `${id}-o-${active}` : undefined}
          aria-invalid={error ? true : undefined}
          aria-describedby={describedBy(id, help, error)}
          onChange={(e) => { setText(e.target.value); setActive(0); setOpen(true); }}
          onClick={() => { if (!open) openList(); }}
          onKeyDown={onKey}
          onBlur={close}
        />
        <button type="button" className={styles.toggle} tabIndex={-1} aria-label={toggleLabel} disabled={disabled}
          onMouseDown={(e) => e.preventDefault()} onClick={() => { if (open) close(); else { openList(); input.current?.focus(); } }}>
          <ChevronDown size={22} aria-hidden="true" />
        </button>
      </div>
      {open ? (
        <ul id={listId} role="listbox" className={styles.list} aria-label={typeof label === 'string' ? label : undefined}>
          {shown.map((o, i) => (
            <li key={o.value} id={`${id}-o-${i}`} role="option" aria-selected={o.value === value} data-active={i === active || undefined}
              className={styles.option} onMouseDown={(e) => e.preventDefault()} onMouseMove={() => setActive(i)} onClick={() => choose(o)}>
              <span className={styles.optLabel}>{o.label}</span>
              {o.hint ? <span className={styles.optHint}>{o.hint}</span> : null}
            </li>
          ))}
          {matches.length === 0 ? <li role="presentation" className={styles.note}>{emptyLabel}</li> : null}
          {matches.length > shown.length ? <li role="presentation" className={styles.note}>{moreLabel(matches.length - shown.length)}</li> : null}
        </ul>
      ) : null}
      </div>
      {help ? <p id={`${id}-help`} className={fieldStyles.help}>{help}</p> : null}
      {error ? <p id={`${id}-error`} className={fieldStyles.error} role="alert"><CircleAlert size={16} aria-hidden="true" /><span>{error}</span></p> : null}
    </div>
  );
}
