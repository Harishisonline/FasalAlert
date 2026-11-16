import { fireEvent, screen } from '@testing-library/react';
import { useState } from 'react';
import { describe, expect, it } from 'vitest';
import { renderWithI18n } from '@/test/utils';
import { Combobox, type ComboOption } from './Combobox';

const OPTIONS: ComboOption[] = [
  { value: '1', label: 'Baramati', search: 'baramati बारामती' },
  { value: '2', label: 'Indapur', search: 'indapur इंदापूर' },
  { value: '3', label: 'Daund', search: 'daund दौंड' },
];

function Harness() {
  const [v, setV] = useState('');
  return (
    <>
      <Combobox id="t" label="Taluka" value={v} options={OPTIONS} onChange={setV} emptyLabel="Nothing matches" moreLabel={(n) => `${n} more`} toggleLabel="Show the list" />
      <output data-testid="value">{v}</output>
    </>
  );
}

describe('Combobox (ONB-02)', () => {
  it('filters as you type in either script and selects with Enter', () => {
    renderWithI18n(<Harness />);
    const box = screen.getByRole('combobox', { name: 'Taluka' });
    fireEvent.change(box, { target: { value: 'इंदा' } });
    expect(screen.getAllByRole('option').map((o) => o.textContent)).toEqual(['Indapur']);
    fireEvent.keyDown(box, { key: 'Enter' });
    expect(screen.getByTestId('value').textContent).toBe('2');
    expect(screen.queryByRole('listbox')).toBeNull();
    expect((box as HTMLInputElement).value).toBe('Indapur');
  });

  it('opens with ArrowDown, moves with the arrows, marks the active option, and Escape restores the choice', () => {
    renderWithI18n(<Harness />);
    const box = screen.getByRole('combobox', { name: 'Taluka' });
    fireEvent.keyDown(box, { key: 'ArrowDown' });
    expect(box.getAttribute('aria-expanded')).toBe('true');
    fireEvent.keyDown(box, { key: 'ArrowDown' });
    expect(box.getAttribute('aria-activedescendant')).toBe('t-o-1');
    fireEvent.keyDown(box, { key: 'Enter' });
    expect(screen.getByTestId('value').textContent).toBe('2');
    fireEvent.change(box, { target: { value: 'zzz' } });
    expect(screen.getByText('Nothing matches')).toBeTruthy();
    fireEvent.keyDown(box, { key: 'Escape' });
    expect((box as HTMLInputElement).value).toBe('Indapur');
    expect(screen.getByTestId('value').textContent).toBe('2');
  });
});
