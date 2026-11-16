'use client';
import { useRef, useState, type KeyboardEvent, type PointerEvent, type ReactNode } from 'react';
import styles from './Chart.module.css';

export interface ReadoutPoint { xPct: number; label: string }

/**
 * Tap readouts, not tooltips (design.md 15.6): tap or drag places a cursor at the nearest point and
 * the readout row above the chart shows its values. Arrow keys move it, Home and End jump, Escape resets.
 */
export function ChartInteractive({ points, summary, ariaLabel, plotLeft, plotRight, children, table, showTableLabel, hideTableLabel, footer }: {
  points: ReadoutPoint[]; summary: string; ariaLabel: string; plotLeft: number; plotRight: number; children: ReactNode;
  table: ReactNode; showTableLabel: string; hideTableLabel: string; footer?: ReactNode;
}) {
  const [idx, setIdx] = useState<number | null>(null);
  const [tableOpen, setTableOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  const nearest = (clientX: number) => {
    const el = ref.current;
    if (!el || points.length === 0) return null;
    const r = el.getBoundingClientRect();
    const w = r.width - plotLeft - plotRight;
    const pct = ((clientX - r.left - plotLeft) / Math.max(1, w)) * 100;
    let best = 0;
    for (let i = 1; i < points.length; i++) if (Math.abs(points[i]!.xPct - pct) < Math.abs(points[best]!.xPct - pct)) best = i;
    return best;
  };
  const onPointer = (e: PointerEvent) => {
    if (e.pointerType === 'mouse' && e.buttons === 0 && e.type === 'pointermove') return;
    const i = nearest(e.clientX);
    if (i !== null) setIdx(i);
  };
  const onKey = (e: KeyboardEvent) => {
    if (points.length === 0) return;
    const last = points.length - 1;
    let next: number | null = idx;
    if (e.key === 'ArrowRight') next = idx === null ? 0 : Math.min(last, idx + 1);
    else if (e.key === 'ArrowLeft') next = idx === null ? last : Math.max(0, idx - 1);
    else if (e.key === 'Home') next = 0;
    else if (e.key === 'End') next = last;
    else if (e.key === 'Escape') next = null;
    else return;
    e.preventDefault();
    setIdx(next);
  };
  const point = idx === null ? null : points[idx];
  return (
    <>
      <p className={styles.readout} aria-live="polite">{point ? point.label : summary}</p>
      <div
        ref={ref}
        className={styles.interactive}
        tabIndex={points.length ? 0 : -1}
        role="group"
        aria-label={ariaLabel}
        onPointerDown={onPointer}
        onPointerMove={onPointer}
        onPointerLeave={() => setIdx(null)}
        onKeyDown={onKey}
        onBlur={() => setIdx(null)}
      >
        {children}
        {point ? (
          <span className={styles.cursor} aria-hidden="true"
            style={{ left: `calc(${plotLeft}px + (100% - ${plotLeft + plotRight}px) * ${point.xPct / 100})` }} />
        ) : null}
      </div>
      <div className={styles.tools}>
        <button type="button" className={styles.tableToggle} aria-expanded={tableOpen} onClick={() => setTableOpen(!tableOpen)}>
          {tableOpen ? hideTableLabel : showTableLabel}
        </button>
        {footer}
      </div>
      <div hidden={!tableOpen} className={styles.tableWrap}>{table}</div>
    </>
  );
}
