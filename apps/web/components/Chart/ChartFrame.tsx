import type { ReactNode } from 'react';
import { ChartInteractive, type ReadoutPoint } from './ChartInteractive';
import styles from './Chart.module.css';

/** Plot geometry. SVG marks use a 0..1000 x range and pixel y (preserveAspectRatio none). */
export const VB_W = 1000;
export const PLOT_LEFT = 48;
export const PLOT_RIGHT = 16;

export interface AxisLabel { y: number; text: string }
export interface XLabel { xPct: number; text: string; align?: 'start' | 'center' | 'end' }
export interface OverlayLabel { xPct: number; y: number; text: string; align?: 'start' | 'end' | 'center'; tone?: 'threshold' | 'muted' | 'strong' | 'event'; below?: boolean }

export interface ChartFrameProps {
  title: string;
  summary: string;
  height: number;
  yLabels: AxisLabel[];
  xLabels: XLabel[];
  overlays?: OverlayLabel[];
  points: ReadoutPoint[];
  table: ReactNode;
  showTableLabel: string;
  hideTableLabel: string;
  ariaLabel: string;
  children: ReactNode;
  footer?: ReactNode;
  head?: ReactNode;
}

/**
 * Server-rendered SVG chart with HTML labels (never below 14px, never stretched) and a client
 * readout row, cursor and "Show as table" toggle (design.md 15.6, 15.8).
 */
export function ChartFrame({ title, summary, height, yLabels, xLabels, overlays = [], points, table, showTableLabel, hideTableLabel, ariaLabel, children, footer, head }: ChartFrameProps) {
  return (
    <figure className={styles.figure}>
      {head}
      <ChartInteractive points={points} summary={summary} ariaLabel={ariaLabel} plotLeft={PLOT_LEFT} plotRight={PLOT_RIGHT}
        table={table} showTableLabel={showTableLabel} hideTableLabel={hideTableLabel} footer={footer}>
        <div className={styles.surface} style={{ height }}>
          <div className={styles.yAxis} aria-hidden="true">
            {yLabels.map((l) => <span key={`${l.y}-${l.text}`} className={styles.yLabel} style={{ top: l.y }}>{l.text}</span>)}
          </div>
          <div className={styles.plot}>
            <svg className={styles.svg} viewBox={`0 0 ${VB_W} ${height}`} preserveAspectRatio="none" width="100%" height={height} role="img" aria-label={title}>
              <title>{title}</title>
              <desc>{summary}</desc>
              <g aria-hidden="true">{children}</g>
            </svg>
            {overlays.map((o, i) => (
              <span key={i} className={styles.overlay} data-align={o.align ?? 'start'} data-tone={o.tone} data-below={o.below || undefined} aria-hidden="true"
                style={{ left: `${o.xPct}%`, top: o.y }}>
                {o.text}
              </span>
            ))}
          </div>
        </div>
        <div className={styles.xAxis} aria-hidden="true">
          {xLabels.map((l, i) => <span key={i} className={styles.xLabel} data-align={l.align ?? 'center'} style={{ left: `${l.xPct}%` }}>{l.text}</span>)}
        </div>
      </ChartInteractive>
    </figure>
  );
}

/* ---- SVG marks (inside the 0..1000 by height viewBox) ---- */

export function GridLines({ ys }: { ys: number[] }) {
  return <>{ys.map((y) => <line key={y} x1={0} x2={VB_W} y1={y} y2={y} className={styles.grid} vectorEffect="non-scaling-stroke" />)}</>;
}

export function PathMark({ d, className, dash }: { d: string | null; className: string; dash?: boolean }) {
  if (!d) return null;
  return <path d={d} className={[styles.mark, className, dash ? styles.dash : ''].join(' ')} vectorEffect="non-scaling-stroke" />;
}

/** Round dots drawn as zero-length round-cap strokes so they stay circular under non-uniform scaling. */
export function Dots({ points, className, hollow }: { points: { x: number; y: number }[]; className: string; hollow?: boolean }) {
  const d = points.map((p) => `M${p.x.toFixed(1)} ${p.y.toFixed(1)}h0`).join('');
  if (!d) return null;
  return (
    <>
      <path d={d} className={[styles.dot, className].join(' ')} vectorEffect="non-scaling-stroke" />
      {hollow ? <path d={d} className={styles.dotHole} vectorEffect="non-scaling-stroke" /> : null}
    </>
  );
}

export function VRule({ x, top, bottom, className }: { x: number; top: number; bottom: number; className: string }) {
  return <line x1={x} x2={x} y1={top} y2={bottom} className={className} vectorEffect="non-scaling-stroke" />;
}

export function HRule({ y, className }: { y: number; className: string }) {
  return <line x1={0} x2={VB_W} y1={y} y2={y} className={className} vectorEffect="non-scaling-stroke" />;
}

export { styles as chartStyles };
