import { PATTERNS } from './patterns';

/** SVG <pattern> definitions matching the map patterns (design.md 16.4). */
export function SvgPatternDefs({ idPrefix = 'fa-pat' }: { idPrefix?: string }) {
  return (
    <defs>
      {Object.entries(PATTERNS).map(([level, spec]) => {
        if (!spec) return null;
        const size = spec.step * 2;
        const stroke = { stroke: `var(${spec.strokeVar})`, fill: `var(${spec.strokeVar})`, strokeWidth: spec.width };
        const s = spec.step;
        let body = null;
        if (spec.kind === 'dots') {
          body = <g style={{ fill: `var(${spec.strokeVar})` }}>{[s / 2, s * 1.5].flatMap((x) => [s / 2, s * 1.5].map((y) => <circle key={`${x}-${y}`} cx={x} cy={y} r={spec.width / 2 + 0.2} />))}</g>;
        } else if (spec.kind === 'horizontal') {
          body = <g style={stroke}>{[s / 2, s * 1.5].map((y) => <line key={y} x1={0} x2={size} y1={y} y2={y} />)}</g>;
        } else {
          const lines = [];
          for (let k = -size; k <= size * 2; k += s) lines.push(<line key={`a${k}`} x1={k} y1={0} x2={k + size} y2={size} />);
          if (spec.kind === 'cross') for (let k = -size; k <= size * 2; k += s) lines.push(<line key={`b${k}`} x1={k} y1={size} x2={k + size} y2={0} />);
          body = <g style={stroke}>{lines}</g>;
        }
        return (
          <pattern key={level} id={`${idPrefix}-${level}`} width={size} height={size} patternUnits="userSpaceOnUse">
            {body}
          </pattern>
        );
      })}
    </defs>
  );
}
