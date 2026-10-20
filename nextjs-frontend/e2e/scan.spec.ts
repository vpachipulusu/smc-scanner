import { expect, test } from './fixtures';

test('scan lists the hits for the demo source', async ({ page }) => {
  await page.goto('/scan');
  await page.getByLabel('Source').selectOption('demo');
  await page.getByRole('button', { name: 'Scan', exact: true }).click();

  await expect(page).toHaveURL(/source=demo/);
  await expect(page.getByTestId('scan-summary')).toHaveText('2 hits on 1h (demo).');
  const table = page.getByRole('table', { name: /touching or near a fresh zone/i });
  await expect(table.getByText('EURUSD', { exact: true })).toBeVisible();
  await expect(table.getByText('XAUUSD', { exact: true })).toBeVisible();
  await expect(page.getByRole('link', { name: 'Download CSV' })).toBeVisible();
});

test('Analyse with AI shows the fake provider verdicts', async ({ page }) => {
  await page.goto('/scan?source=demo');
  await page.getByRole('button', { name: 'Analyse with AI' }).click();

  await expect(page.getByText('2 of 2 hits analysed.')).toBeVisible();
  const table = page.getByRole('table', { name: /touching or near a fresh zone/i });
  await expect(table.getByText('BUY', { exact: true })).toBeVisible();
  await expect(table.getByText('SELL', { exact: true })).toBeVisible();
  await expect(page.getByTestId('ai-skipped')).toHaveCount(0);
});
