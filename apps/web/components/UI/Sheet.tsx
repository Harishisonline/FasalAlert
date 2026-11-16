'use client';
import { useEffect, useId, useRef, useState, type PointerEvent, type ReactNode } from 'react';
import { X } from '@/components/Icon';
import styles from './Sheet.module.css';

/**
 * Bottom sheet (design.md A.13): preset heights 50% and 90%, a drag handle that is also a button
 * (single-pointer alternative to dragging), a close button. Modal sheets trap focus via <dialog>;
 * non-modal sheets leave the page interactive.
 */
export function Sheet({ open, onClose, title, children, modal = true, expandLabel, collapseLabel, closeLabel, initial = 'half', className }: {
  open: boolean; onClose: () => void; title: ReactNode; children: ReactNode; modal?: boolean;
  expandLabel: string; collapseLabel: string; closeLabel: string; initial?: 'half' | 'full'; className?: string;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const [size, setSize] = useState<'half' | 'full'>(initial);
  const startY = useRef<number | null>(null);
  const id = useId();

  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) {
      setSize(initial);
      if (modal) d.showModal(); else d.show();
    } else if (!open && d.open) {
      d.close();
    }
  }, [open, modal, initial]);

  const onPointerDown = (e: PointerEvent) => { startY.current = e.clientY; };
  const onPointerUp = (e: PointerEvent) => {
    if (startY.current === null) return;
    const dy = e.clientY - startY.current;
    startY.current = null;
    if (dy < -40) setSize('full');
    else if (dy > 80) { if (size === 'full') setSize('half'); else onClose(); }
  };

  return (
    <dialog
      ref={ref}
      className={[styles.sheet, className ?? ''].join(' ')}
      data-size={size}
      data-modal={modal || undefined}
      aria-labelledby={`${id}-t`}
      onCancel={(e) => { e.preventDefault(); onClose(); }}
      onClick={(e) => { if (modal && e.target === ref.current) onClose(); }}
    >
      <div className={styles.inner}>
        <div className={styles.top} onPointerDown={onPointerDown} onPointerUp={onPointerUp}>
          <button
            type="button"
            className={styles.handle}
            aria-label={size === 'half' ? expandLabel : collapseLabel}
            onClick={() => setSize(size === 'half' ? 'full' : 'half')}
          >
            <span className={styles.bar} aria-hidden="true" />
          </button>
          <div className={styles.header}>
            <h2 id={`${id}-t`} className={styles.title}>{title}</h2>
            <button type="button" className={styles.close} aria-label={closeLabel} onClick={onClose}>
              <X size={24} aria-hidden="true" />
            </button>
          </div>
        </div>
        <div className={styles.content}>{children}</div>
      </div>
    </dialog>
  );
}
