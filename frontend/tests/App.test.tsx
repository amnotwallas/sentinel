import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { App } from '../src/App';

describe('foundation shell', () => {
  it('explains the current milestone and offers a keyboard accessible health link', () => {
    render(<App />);
    expect(
      screen.getByRole('heading', { name: 'Sentinel', level: 1 }),
    ).toBeVisible();
    expect(
      screen.getByText(/Foundation is ready for development/),
    ).toBeVisible();
    expect(screen.getByRole('link', { name: 'API readiness' })).toHaveAttribute(
      'href',
      '/health/ready',
    );
  });
});
