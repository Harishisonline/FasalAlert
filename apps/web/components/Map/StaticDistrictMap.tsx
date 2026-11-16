import type { SvgMap } from '@/lib/geo';
import type { DisplayLevel } from '@/lib/risk';
import { PATTERNS } from './patterns';
import { SvgPatternDefs } from './SvgPatterns';
import styles from './StaticDistrictMap.module.css';

/**
 * The SVG district map generated from the boundary GeoJSON. With no levels it is the loading
 * skeleton; with levels it is the WebGL-unavailable fallback, coloured and patterned (design.md 12.1).
 */
export function StaticDistrictMap({ map, levels, selected, label, pulse }: { map: SvgMap; levels?: Record<string, DisplayLevel>; selected?: string | null; label?: string; pulse?: boolean }) {
  return (
    <svg
      viewBox={`0 0 ${map.width} ${map.height}`}
      className={styles.map}
      data-skeleton={!levels || undefined}
      data-pulse={pulse || undefined}
      role={label ? 'img' : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : true}
      preserveAspectRatio="xMidYMid meet"
    >
      <SvgPatternDefs />
      {map.districts.map((d) => {
        const level = levels ? (levels[d.code] ?? 'nodata') : undefined;
        return (
          <g key={d.code}>
            <path d={d.d} className={styles.district} data-level={level} data-selected={selected === d.code || undefined} />
            {level && PATTERNS[level] ? <path d={d.d} fill={`url(#fa-pat-${level})`} className={styles.pattern} /> : null}
          </g>
        );
      })}
    </svg>
  );
}
