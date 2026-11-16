import type { RiskKind } from '@fasalalert/shared/api';
import {
  CircleCheck, CircleDashed, CloudRain, IndianRupee, Info, OctagonAlert, Siren, Snowflake, Sun,
  ThermometerSun, TriangleAlert, Truck, type LucideIcon,
} from 'lucide-react';
import type { DisplayLevel } from '@/lib/risk';

const LEVEL_ICONS: Record<DisplayLevel, LucideIcon> = {
  none: CircleCheck, low: Info, medium: TriangleAlert, high: OctagonAlert, critical: Siren, nodata: CircleDashed,
};
const KIND_ICONS: Record<RiskKind | 'price', LucideIcon> = {
  frost: Snowflake, heatwave: ThermometerSun, heavy_rain: CloudRain, dry_spell: Sun, transport: Truck, price: IndianRupee,
};

interface Props { size?: number; className?: string }

/** Level icon (design.md 6.4): every level has an icon as well as a colour and a word. */
export function LevelIcon({ level, size = 20, className }: Props & { level: DisplayLevel }) {
  const Icon = LEVEL_ICONS[level];
  return <Icon size={size} absoluteStrokeWidth strokeWidth={2} aria-hidden="true" focusable="false" className={className} />;
}

export function KindIcon({ kind, size = 20, className }: Props & { kind: RiskKind | 'price' }) {
  const Icon = KIND_ICONS[kind] ?? Info;
  return <Icon size={size} absoluteStrokeWidth strokeWidth={2} aria-hidden="true" focusable="false" className={className} />;
}
