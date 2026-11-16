/**
 * The FasalAlert mark (design.md 5.2): a leaf-green rounded square holding a two-leaf sprout and a
 * dashed threshold line. Drawn by hand on a 48 grid. Below 32px the dashed line is dropped.
 */
export function LogoMark({ size = 32, className, title }: { size?: number; className?: string; title?: string }) {
  const showLine = size >= 32;
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 48 48"
      className={className}
      role={title ? 'img' : undefined}
      aria-hidden={title ? undefined : true}
      aria-label={title}
      focusable="false"
    >
      <rect x="4" y="4" width="40" height="40" rx="10" fill="var(--color-logo-fill, #0b5c2e)" />
      <g fill="none" stroke="#ffffff" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
        {showLine ? <path d="M10 30H38" strokeDasharray="3 2" strokeLinecap="butt" /> : null}
        <path d="M24 38V21" />
        <path d="M24 25C22.5 19.5 18 16 12 16.5c.5 5.5 5 9 12 8.5z" />
        <path d="M24 21.5c1.5-6 6.5-9.5 12-9 0 5.5-4.5 9.5-12 9z" />
      </g>
    </svg>
  );
}
