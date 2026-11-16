import { forwardRef, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes } from 'react';
import { ChevronDown, CircleAlert } from '@/components/Icon';
import styles from './Field.module.css';

interface Wrap { id: string; label: ReactNode; help?: ReactNode; error?: ReactNode; suffix?: ReactNode; size?: 'lg' | 'md' }

export function FieldMessage({ id, error, help }: { id: string; error?: ReactNode; help?: ReactNode }) {
  return (
    <>
      {help ? <p id={`${id}-help`} className={styles.help}>{help}</p> : null}
      {error ? (
        <p id={`${id}-error`} className={styles.error} role="alert">
          <CircleAlert size={16} aria-hidden="true" />
          <span>{error}</span>
        </p>
      ) : null}
    </>
  );
}

export function describedBy(id: string, help?: unknown, error?: unknown): string | undefined {
  const ids = [help ? `${id}-help` : '', error ? `${id}-error` : ''].filter(Boolean);
  return ids.length ? ids.join(' ') : undefined;
}

export const TextField = forwardRef<HTMLInputElement, Wrap & Omit<InputHTMLAttributes<HTMLInputElement>, 'id' | 'size'>>(
  function TextField({ id, label, help, error, suffix, size = 'lg', className, ...rest }, ref) {
    return (
      <div className={[styles.field, className ?? ''].join(' ')}>
        <label htmlFor={id} className={styles.label}>{label}</label>
        <div className={styles.control} data-size={size} data-invalid={error ? true : undefined}>
          <input ref={ref} id={id} {...rest} aria-invalid={error ? true : undefined} aria-describedby={describedBy(id, help, error)} className={styles.input} />
          {suffix ? <span className={styles.suffix} aria-hidden="true">{suffix}</span> : null}
        </div>
        <FieldMessage id={id} help={help} error={error} />
      </div>
    );
  },
);

export function SelectField({ id, label, help, error, size = 'lg', className, children, ...rest }: Wrap & Omit<SelectHTMLAttributes<HTMLSelectElement>, 'id' | 'size'>) {
  return (
    <div className={[styles.field, className ?? ''].join(' ')}>
      <label htmlFor={id} className={styles.label}>{label}</label>
      <div className={styles.control} data-size={size} data-invalid={error ? true : undefined} data-select>
        <select id={id} {...rest} aria-invalid={error ? true : undefined} aria-describedby={describedBy(id, help, error)} className={styles.input}>
          {children}
        </select>
        <ChevronDown size={24} aria-hidden="true" className={styles.chevron} />
      </div>
      <FieldMessage id={id} help={help} error={error} />
    </div>
  );
}
