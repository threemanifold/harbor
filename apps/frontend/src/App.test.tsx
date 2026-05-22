import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import App from './App';

describe('App', () => {
  it('renders the title', () => {
    render(<App />);
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(
      'Harbor',
    );
  });

  it('starts the counter at 0', () => {
    render(<App />);
    expect(screen.getByText('Count: 0')).toBeInTheDocument();
  });
});
