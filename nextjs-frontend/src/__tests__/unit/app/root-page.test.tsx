/** The scan route has a loading state while the server scans. */
import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import ScanLoading from '@/app/scan/loading';

describe('ScanLoading', () => {
  it('announces that a scan is running', () => {
    render(<ScanLoading />);

    expect(screen.getByRole('status', { name: 'Scanning' })).toBeInTheDocument();
  });
});
