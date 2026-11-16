import { expect, type Page } from '@playwright/test';
import { readFileSync, existsSync } from 'node:fs';
import path from 'node:path';

/** The dev SMS outbox the API writes OTP messages to (SMS_PROVIDER=dev_outbox, development only). */
const OUTBOX = path.join(process.env.DEV_OUTBOX_DIR || path.resolve(import.meta.dirname, '..', '..', 'api', 'data', 'dev_outbox'), 'sms.jsonl');

/** A fresh test phone number for this run (10 digits, starts with 9). Nothing is ever sent to it. */
export function testPhone(): string {
  return `9${String(Date.now()).slice(-9)}`;
}

/** The newest code written to the outbox for this number after `since` (the test reads it; it is never logged). */
export async function readOtp(digits: string, since: number): Promise<string> {
  const to = `+91${digits}`;
  for (let i = 0; i < 40; i++) {
    if (existsSync(OUTBOX)) {
      const lines = readFileSync(OUTBOX, 'utf8').trim().split('\n').filter(Boolean).map((l) => JSON.parse(l) as { to: string; at: string; body: string });
      const hit = lines.filter((m) => m.to === to && Date.parse(m.at) >= since - 2000).pop();
      if (hit) return hit.body.split('#').pop()!.trim();
    }
    await new Promise((r) => setTimeout(r, 250));
  }
  throw new Error(`no OTP in ${OUTBOX} for the test number`);
}

/** Sign in through the real UI: phone, Send, the code from the dev outbox. Waits out the 60 s resend guard. */
export async function signIn(page: Page, digits: string): Promise<void> {
  await page.getByLabel('Mobile number').fill(digits);
  const send = page.getByRole('button', { name: /Send OTP|Resend code in/ });
  await expect(send).toBeEnabled({ timeout: 90_000 });
  const since = Date.now();
  await page.getByRole('button', { name: 'Send OTP' }).click();
  // A second sign-in for the same number within 60 s is refused by the API; the button counts down, then we retry.
  const codeInput = page.locator('input[autocomplete="one-time-code"]');
  const phoneLocked = page.getByRole('button', { name: /Resend code in/ }).and(page.locator('form:has(input[type="tel"]) button'));
  await expect(codeInput.or(phoneLocked).first()).toBeVisible();
  if (!(await codeInput.isVisible())) {
    await expect(page.getByRole('button', { name: 'Send OTP' })).toBeEnabled({ timeout: 90_000 });
    await page.getByRole('button', { name: 'Send OTP' }).click();
  }
  await expect(codeInput).toBeVisible();
  // Development and demo servers say no SMS was sent (signin.devNotice or signin.demoTitle).
  await expect(page.getByText(/Development server: no SMS was sent\.|DEMO MODE: SMS delivery is disabled\./)).toBeVisible();
  const code = await readOtp(digits, since);
  await codeInput.fill(code);
}

/** Pick an option in one of the onboarding comboboxes by typing, then choosing the first match. */
export async function chooseFromCombobox(page: Page, label: string, text: string): Promise<void> {
  const box = page.getByRole('combobox', { name: label });
  await expect(box).toBeEnabled({ timeout: 20_000 });
  await box.click();
  await box.fill(text);
  const option = page.getByRole('option').first();
  await expect(option).toBeVisible();
  await option.click();
}

/** No horizontal page scroll: the document is never wider than the viewport. */
export async function expectNoHorizontalOverflow(page: Page, where: string): Promise<void> {
  const { doc, vw, culprits } = await page.evaluate(() => {
    const vw = document.documentElement.clientWidth;
    const culprits = [...document.querySelectorAll('body *')]
      .filter((e) => { const r = e.getBoundingClientRect(); return r.width > 0 && r.right > vw + 1 && getComputedStyle(e).position !== 'fixed'; })
      .slice(0, 3).map((e) => `${e.tagName.toLowerCase()}.${String((e as HTMLElement).className).slice(0, 40)}`);
    return { doc: document.documentElement.scrollWidth, vw, culprits };
  });
  expect(doc, `${where}: page is ${doc}px wide in a ${vw}px viewport (${culprits.join(', ')})`).toBeLessThanOrEqual(vw + 1);
}

export async function mapBox(page: Page) {
  const box = await page.locator('[data-testid="map-box"]').boundingBox();
  if (!box) throw new Error('map box not found');
  return box;
}
