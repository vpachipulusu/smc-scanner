/** Schedule form toggles and the summary in the schedule row. */
import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { makeSchedule } from '../../helpers/automation-fixtures';

vi.mock('@/app/automation/actions', () => ({
  saveScheduleAction: vi.fn(),
  toggleScheduleAction: vi.fn(),
  runScheduleAction: vi.fn(),
  deleteScheduleAction: vi.fn(),
}));
vi.mock('next/navigation', () => ({ useRouter: () => ({ refresh: vi.fn() }) }));

import { ScheduleForm } from '@/components/automation/schedule-form';
import { SchedulesTable } from '@/components/automation/schedules-table';

const MTF = 'Include higher/lower timeframe context';
const REQUIRE = 'Require higher-timeframe alignment';

describe('ScheduleForm multi-timeframe options', () => {
  it('has both options off, the second disabled, and explains the cost', () => {
    render(<ScheduleForm />);

    expect(screen.getByLabelText(MTF)).not.toBeChecked();
    expect(screen.getByLabelText(MTF)).toHaveAttribute('name', 'mtf');
    expect(screen.getByLabelText(REQUIRE)).toBeDisabled();
    expect(screen.getByLabelText(REQUIRE)).toHaveAttribute('name', 'require_htf_aligned');
    expect(screen.getByText(/roughly triples/i)).toBeInTheDocument();
  });

  it('enables the second option once mtf is on', async () => {
    const user = userEvent.setup();
    render(<ScheduleForm />);

    await user.click(screen.getByLabelText(MTF));
    expect(screen.getByLabelText(REQUIRE)).toBeEnabled();
  });

  it('starts from the schedule being edited', () => {
    render(<ScheduleForm schedule={makeSchedule({ mtf: true, require_htf_aligned: true })} />);

    expect(screen.getByLabelText(MTF)).toBeChecked();
    expect(screen.getByLabelText(REQUIRE)).toBeChecked();
    expect(screen.getByLabelText(REQUIRE)).toBeEnabled();
  });
});

describe('SchedulesTable multi-timeframe summary', () => {
  it('shows nothing extra when both are off', () => {
    render(<SchedulesTable schedules={[makeSchedule()]} />);

    expect(screen.queryByText('Multi-timeframe')).not.toBeInTheDocument();
    expect(screen.queryByText('HTF aligned only')).not.toBeInTheDocument();
  });

  it('shows the pills that are on', () => {
    render(
      <SchedulesTable
        schedules={[
          makeSchedule({ id: 1, mtf: true }),
          makeSchedule({ id: 2, mtf: true, require_htf_aligned: true }),
        ]}
      />
    );

    expect(screen.getAllByText('Multi-timeframe')).toHaveLength(2);
    expect(screen.getAllByText('HTF aligned only')).toHaveLength(1);
  });
});
