import type { Crop } from '@fasalalert/shared/api';

export interface ShellField { id: number; name: string; crop: Crop; stageLabel: string | null }
export interface ShellData {
  signedIn: boolean;
  user: { name: string | null; phoneMasked: string } | null;
  fields: ShellField[];
  unread: number;
}
export type { Destination as TabKey } from '@/lib/nav';
