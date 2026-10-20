import { expect, test } from './fixtures';

const SCHEDULE_NAME = 'Gold hourly';

test('automation: create, toggle, run now, view logs and delete a schedule', async ({ page }) => {
  await page.goto('/automation');
  await expect(page.getByTestId('no-schedules')).toBeVisible();

  // Create
  const form = page.getByRole('form', { name: 'New schedule' });
  await form.getByLabel('Name').fill(SCHEDULE_NAME);
  await form.getByLabel('Source').selectOption('demo');
  await form.getByLabel('Symbols').fill('XAUUSD, EURUSD');
  await form.getByRole('button', { name: 'Create schedule' }).click();
  await expect(page.getByText(`Schedule "${SCHEDULE_NAME}" created.`)).toBeVisible();
  const table = page.getByRole('table', { name: 'Schedules' });
  const row = table.getByRole('row', { name: new RegExp(SCHEDULE_NAME) });
  await expect(table.getByText(SCHEDULE_NAME)).toBeVisible();
  await expect(row.getByText('Enabled', { exact: true })).toBeVisible();

  // Run now, then the job log shows the run
  await page.getByRole('button', { name: `Run now: ${SCHEDULE_NAME}` }).click();
  await expect(page.getByText('Run finished: 2 hits, 0 delivered, 2 skipped.')).toBeVisible();
  await page.getByRole('link', { name: `Logs: ${SCHEDULE_NAME}` }).click();
  await expect(page.getByRole('heading', { level: 1, name: /Job log/ })).toBeVisible();
  const logRow = page
    .getByRole('table', { name: 'Job log' })
    .getByRole('row', { name: /telegram disabled/ });
  await expect(logRow).toContainText('Success');
  await page.getByRole('link', { name: 'Back to automation' }).click();

  // Toggle
  await page.getByRole('button', { name: `Disable: ${SCHEDULE_NAME}` }).click();
  await expect(page.getByText('Schedule disabled.')).toBeVisible();
  await expect(row.getByText('Disabled', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: `Enable: ${SCHEDULE_NAME}` }).click();
  await expect(page.getByText('Schedule enabled.')).toBeVisible();

  // Delete asks for confirmation; cancelling keeps the row
  await page.getByRole('button', { name: `Delete: ${SCHEDULE_NAME}` }).click();
  await page.getByRole('button', { name: 'Cancel' }).click();
  await expect(table.getByText(SCHEDULE_NAME)).toBeVisible();

  await page.getByRole('button', { name: `Delete: ${SCHEDULE_NAME}` }).click();
  await page.getByRole('button', { name: 'Confirm delete' }).click();
  await expect(page.getByTestId('no-schedules')).toBeVisible();
});

test('automation rejects an invalid schedule with a field message', async ({ page }) => {
  await page.goto('/automation');
  const form = page.getByRole('form', { name: 'New schedule' });
  await form.getByLabel('Name').fill('Bad symbols');
  await form.getByLabel('Symbols').fill('EUR/USD!');
  await form.getByRole('button', { name: 'Create schedule' }).click();

  await expect(form.getByLabel('Symbols')).toHaveAttribute('aria-invalid', 'true');
  await expect(form.getByLabel('Symbols')).toBeFocused();
  await expect(page.getByTestId('no-schedules')).toBeVisible();
});

test('the job log of an unknown schedule is not found', async ({ page }) => {
  // notFound() streams after the loading shell, so the status is 200; assert the rendered page.
  await page.goto('/automation/999/logs');
  await expect(page.getByRole('heading', { name: /could not be found/i })).toBeVisible();
});
