'use client';
/**
 * Earcons generated with the Web Audio API, so there are no audio files to license or download
 * (design.md 17.5). Haptics where navigator.vibrate exists.
 */
let ctx: AudioContext | null = null;
const PREF_KEY = 'fa:earcons';

export function earconsEnabled(): boolean {
  try { return localStorage.getItem(PREF_KEY) !== 'off'; } catch { return true; }
}

function context(): AudioContext | null {
  if (typeof window === 'undefined') return null;
  const AC = window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
  if (!AC) return null;
  if (!ctx) ctx = new AC();
  if (ctx.state === 'suspended') void ctx.resume();
  return ctx;
}

function tone(freqs: number[], each: number): void {
  const ac = context();
  if (!ac || !earconsEnabled()) return;
  const start = ac.currentTime;
  freqs.forEach((f, i) => {
    const osc = ac.createOscillator();
    const gain = ac.createGain();
    osc.type = 'sine';
    osc.frequency.value = f;
    const t0 = start + i * each;
    gain.gain.setValueAtTime(0.0001, t0);
    gain.gain.exponentialRampToValueAtTime(0.18, t0 + 0.01);
    gain.gain.exponentialRampToValueAtTime(0.0001, t0 + each);
    osc.connect(gain).connect(ac.destination);
    osc.start(t0);
    osc.stop(t0 + each + 0.02);
  });
}

/** Start: a rising two-note chirp, about 120 ms. */
export function earconStart(): void { tone([660, 880], 0.06); vibrate(30); }
/** Stop or send: a falling two-note chirp, about 120 ms. */
export function earconSend(): void { tone([880, 660], 0.06); vibrate([20, 40, 20]); }
/** Cancel: one low note, about 80 ms. */
export function earconCancel(): void { tone([330], 0.08); }

function vibrate(pattern: number | number[]): void {
  try {
    if (earconsEnabled() && typeof navigator !== 'undefined' && 'vibrate' in navigator) navigator.vibrate(pattern);
  } catch { /* unsupported */ }
}

/** Shared AudioContext for the level meter. */
export function audioContext(): AudioContext | null {
  return context();
}
