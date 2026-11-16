import { act, fireEvent, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { renderWithI18n } from '@/test/utils';

vi.mock('next/navigation', () => ({
  usePathname: () => '/en/signin',
  useSearchParams: () => new URLSearchParams(''),
  useRouter: () => ({ replace: vi.fn(), push: vi.fn(), refresh: vi.fn() }),
}));

const fetchMock = vi.fn();
function json(status: number, body: unknown) {
  return Promise.resolve(new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } }));
}

describe('R2 phone and OTP input behaviour', async () => {
  const { SignInFlow } = await import('./SignInFlow');
  beforeEach(() => { fetchMock.mockReset(); vi.stubGlobal('fetch', fetchMock); });
  afterEach(() => vi.unstubAllGlobals());

  async function toCodeStep(otpBody: Record<string, unknown> = { expires_in: 300, retry_after: 60 }) {
    fetchMock.mockImplementationOnce(() => json(200, otpBody));
    renderWithI18n(<SignInFlow next={null} expired={false} />);
    const phone = screen.getByLabelText('Mobile number');
    fireEvent.paste(phone, { clipboardData: { getData: () => '+91 98765-43210' } });
    expect((phone as HTMLInputElement).value).toBe('98765 43210');
    fireEvent.click(screen.getByRole('button', { name: 'Send OTP' }));
    await screen.findByText('Enter the 6-digit code');
    expect(fetchMock.mock.calls[0]![0]).toBe('/api/auth/otp/request');
    expect(JSON.parse(fetchMock.mock.calls[0]![1].body)).toEqual({ phone: '+919876543210' });
  }

  it('shows the server demo OTP with a copy control when demo_code is returned', async () => {
    await toCodeStep({ expires_in: 300, retry_after: 60, delivery: 'dev_outbox', demo_code: '479161' });
    expect(screen.getByText('DEMO MODE: SMS delivery is disabled.')).toBeTruthy();
    expect(screen.getByText('479161')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Copy code' })).toBeTruthy();
  });

  it('keeps Send disabled and shows an inline error for an invalid number', () => {
    renderWithI18n(<SignInFlow next={null} expired={false} />);
    const phone = screen.getByLabelText('Mobile number');
    fireEvent.change(phone, { target: { value: '12345' } });
    fireEvent.blur(phone);
    expect(screen.getByText('Enter a 10-digit mobile number.')).toBeTruthy();
    expect((screen.getByRole('button', { name: 'Send OTP' }) as HTMLButtonElement).disabled).toBe(true);
  });

  it('one input drawn as 6 boxes: paste distributes digits and the 6th digit submits', async () => {
    await toCodeStep();
    const code = screen.getByLabelText('6-digit code') as HTMLInputElement;
    expect(code.getAttribute('autocomplete')).toBe('one-time-code');
    expect(code.getAttribute('inputmode')).toBe('numeric');
    fetchMock.mockImplementationOnce(() => json(400, { error: { code: 'validation_error', message: 'Wrong code', details: { field: 'code' }, trace_id: 't1' } }));
    await act(async () => { fireEvent.change(code, { target: { value: '12 34 56' } }); });
    const boxes = document.querySelectorAll('[aria-hidden="true"][data-gap], [aria-hidden="true"]');
    expect(boxes.length).toBeGreaterThan(0);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(JSON.parse(fetchMock.mock.calls[1]![1].body)).toEqual({ phone: '+919876543210', code: '123456' });
    expect(await screen.findByText('Wrong code. 4 attempts left.')).toBeTruthy();
    expect(code.value).toBe('');
  });

  it('locks after 5 failures with the helpline', async () => {
    await toCodeStep();
    const code = screen.getByLabelText('6-digit code') as HTMLInputElement;
    fetchMock.mockImplementation(() => json(400, { error: { code: 'validation_error', message: 'Wrong', details: { attempts_left: 0 }, trace_id: '' } }));
    await act(async () => { fireEvent.change(code, { target: { value: '000000' } }); });
    expect(await screen.findByText('Too many attempts. Call 1800-180-1551 for help.')).toBeTruthy();
    expect((screen.getByRole('button', { name: 'Verify' }) as HTMLButtonElement).disabled).toBe(true);
  });

  it('shows the rate limit with the server retry_after', async () => {
    fetchMock.mockImplementationOnce(() => json(429, { error: { code: 'rate_limited', message: 'slow down', details: { retry_after: 2280 }, trace_id: '' } }));
    renderWithI18n(<SignInFlow next={null} expired={false} />);
    fireEvent.change(screen.getByLabelText('Mobile number'), { target: { value: '9876543210' } });
    fireEvent.click(screen.getByRole('button', { name: 'Send OTP' }));
    expect(await screen.findByText('Too many codes requested. Try again in 38 min.')).toBeTruthy();
  });
});
