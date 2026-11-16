'use client';
/**
 * Microphone capture for R5 (design.md 17.6): getUserMedia with a 10 s permission timeout,
 * MediaRecorder with the codec negotiated through isTypeSupported(), and an RMS level meter from an
 * AnalyserNode on each animation frame.
 */
import { audioContext } from '@/lib/audio';

export type StartResult = 'ok' | 'denied' | 'timeout' | 'unsupported';
export interface Recording { blob: Blob; mime: string; peak: number; durationMs: number }

const MIME_PREFERENCE = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4', 'audio/ogg;codecs=opus'];

export function recordingSupported(): boolean {
  return typeof window !== 'undefined' && Boolean(navigator.mediaDevices?.getUserMedia) && typeof MediaRecorder !== 'undefined';
}

export class Recorder {
  private stream: MediaStream | null = null;
  private recorder: MediaRecorder | null = null;
  private chunks: Blob[] = [];
  private raf = 0;
  private peak = 0;
  private startedAt = 0;
  private mime = '';
  onLevel: ((rms: number) => void) | null = null;

  async start(): Promise<StartResult> {
    if (!recordingSupported()) return 'unsupported';
    let stream: MediaStream;
    try {
      const result = await Promise.race([
        navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true } }),
        new Promise<'timeout'>((r) => setTimeout(() => r('timeout'), 10_000)),
      ]);
      if (result === 'timeout') return 'timeout';
      stream = result;
    } catch (e) {
      return e instanceof DOMException && (e.name === 'NotAllowedError' || e.name === 'SecurityError') ? 'denied' : 'unsupported';
    }
    this.stream = stream;
    this.mime = MIME_PREFERENCE.find((m) => MediaRecorder.isTypeSupported?.(m)) ?? '';
    try {
      this.recorder = new MediaRecorder(stream, this.mime ? { mimeType: this.mime } : undefined);
    } catch {
      this.release();
      return 'unsupported';
    }
    this.chunks = [];
    this.peak = 0;
    this.recorder.ondataavailable = (e) => { if (e.data.size) this.chunks.push(e.data); };
    this.recorder.start(250);
    this.startedAt = performance.now();
    this.meter(stream);
    return 'ok';
  }

  private meter(stream: MediaStream) {
    const ac = audioContext();
    if (!ac) return;
    const src = ac.createMediaStreamSource(stream);
    const analyser = ac.createAnalyser();
    analyser.fftSize = 1024;
    src.connect(analyser);
    const data = new Uint8Array(analyser.fftSize);
    const tick = () => {
      analyser.getByteTimeDomainData(data);
      let sum = 0;
      for (let i = 0; i < data.length; i++) {
        const v = (data[i]! - 128) / 128;
        sum += v * v;
      }
      const rms = Math.sqrt(sum / data.length);
      if (rms > this.peak) this.peak = rms;
      this.onLevel?.(rms);
      this.raf = requestAnimationFrame(tick);
    };
    this.raf = requestAnimationFrame(tick);
  }

  elapsedMs(): number {
    return this.startedAt ? performance.now() - this.startedAt : 0;
  }

  stop(): Promise<Recording | null> {
    cancelAnimationFrame(this.raf);
    const rec = this.recorder;
    if (!rec || rec.state === 'inactive') { this.release(); return Promise.resolve(null); }
    return new Promise((resolve) => {
      rec.onstop = () => {
        const mime = rec.mimeType || this.mime || 'audio/webm';
        const blob = new Blob(this.chunks, { type: mime });
        const out = { blob, mime, peak: this.peak, durationMs: this.elapsedMs() };
        this.release();
        resolve(out);
      };
      rec.stop();
    });
  }

  cancel() {
    cancelAnimationFrame(this.raf);
    try { this.recorder?.stop(); } catch { /* already stopped */ }
    this.release();
  }

  private release() {
    this.stream?.getTracks().forEach((tr) => tr.stop());
    this.stream = null;
    this.recorder = null;
    this.startedAt = 0;
  }
}

export function blobToBase64(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(String(r.result).replace(/^data:[^,]*,/, ''));
    r.onerror = () => reject(r.error);
    r.readAsDataURL(blob);
  });
}

export async function micPermissionState(): Promise<PermissionState | 'unknown'> {
  try {
    const p = await navigator.permissions?.query({ name: 'microphone' as PermissionName });
    return p?.state ?? 'unknown';
  } catch {
    return 'unknown';
  }
}
