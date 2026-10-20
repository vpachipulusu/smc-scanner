/** The root redirects to /scan; the scan route has a loading state while the server scans. */
import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { redirect } from 'next/navigation';
import HomePage from '@/app/page';
import ScanLoading from '@/app/scan/loading';

describe('HomePage', () => {
  it('redirects to the scan page', () => {
    HomePage();

    expect(vi.mocked(redirect)).toHaveBeenCalledWith('/scan');
  });
});

describe('ScanLoading', () => {
  it('announces that a scan is running', () => {
    render(<ScanLoading />);

    expect(screen.getByRole('status', { name: 'Scanning' })).toBeInTheDocument();
  });
});
