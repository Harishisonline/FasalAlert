'use client';
/**
 * Offline helpers (design.md 20.5). The last known decisions are kept on this phone so R10 can show
 * them; questions asked while offline are kept in IndexedDB and offered for retry (PRD §7.5).
 */
import type { Abstention, Decision, Field } from '@fasalalert/shared/api';

const SNAPSHOT_KEY = 'fa:last-known';
const DB_NAME = 'fasalalert';
const STORE = 'pending-questions';

export interface LastKnownSnapshot {
  savedAt: string;
  fields: Pick<Field, 'id' | 'name' | 'crop' | 'variety'>[];
  decisions: (Decision | Abstention)[];
  kvk: { name: string; phone: string } | null;
}

export function saveSnapshot(s: LastKnownSnapshot): void {
  try { localStorage.setItem(SNAPSHOT_KEY, JSON.stringify(s)); } catch { /* storage may be unavailable */ }
}

export function readSnapshot(): LastKnownSnapshot | null {
  try {
    const raw = localStorage.getItem(SNAPSHOT_KEY);
    return raw ? (JSON.parse(raw) as LastKnownSnapshot) : null;
  } catch {
    return null;
  }
}

export interface PendingQuestion {
  id?: number;
  text?: string;
  audio_b64?: string;
  audio_mime?: string;
  field_id?: number;
  locale: string;
  savedAt: string;
}

function openDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    if (typeof indexedDB === 'undefined') return reject(new Error('no indexedDB'));
    const req = indexedDB.open(DB_NAME, 1);
    req.onupgradeneeded = () => {
      if (!req.result.objectStoreNames.contains(STORE)) req.result.createObjectStore(STORE, { keyPath: 'id', autoIncrement: true });
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

export async function savePendingQuestion(q: PendingQuestion): Promise<number | null> {
  try {
    const db = await openDb();
    return await new Promise((resolve, reject) => {
      const tx = db.transaction(STORE, 'readwrite');
      const req = tx.objectStore(STORE).add(q);
      req.onsuccess = () => resolve(req.result as number);
      req.onerror = () => reject(req.error);
    });
  } catch {
    return null;
  }
}

export async function deletePendingQuestion(id: number): Promise<void> {
  try {
    const db = await openDb();
    await new Promise<void>((resolve) => {
      const tx = db.transaction(STORE, 'readwrite');
      tx.objectStore(STORE).delete(id);
      tx.oncomplete = () => resolve();
      tx.onerror = () => resolve();
    });
  } catch { /* nothing to delete */ }
}

export async function listPendingQuestions(): Promise<PendingQuestion[]> {
  try {
    const db = await openDb();
    return await new Promise((resolve) => {
      const req = db.transaction(STORE, 'readonly').objectStore(STORE).getAll();
      req.onsuccess = () => resolve(req.result as PendingQuestion[]);
      req.onerror = () => resolve([]);
    });
  } catch {
    return [];
  }
}

/** Remove everything personal from this device (sign out). */
export async function clearDeviceData(): Promise<void> {
  try { localStorage.removeItem(SNAPSHOT_KEY); } catch { /* ignore */ }
  try {
    if (typeof indexedDB !== 'undefined') indexedDB.deleteDatabase(DB_NAME);
  } catch { /* ignore */ }
  try {
    if (typeof caches !== 'undefined') {
      const names = await caches.keys();
      await Promise.all(names.filter((n) => n.startsWith('fa-api') || n.startsWith('pages')).map((n) => caches.delete(n)));
    }
  } catch { /* ignore */ }
}
