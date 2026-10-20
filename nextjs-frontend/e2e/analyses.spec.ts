import { expect, test } from './fixtures';

test('analyses filters round-trip through the URL and reset', async ({ page }) => {
  await page.goto('/analyses');
  await expect(page.getByTestId('history-row')).toHaveCount(3);

  await page.getByLabel('Symbol').fill('EURUSD');
  await page.getByLabel('Action').selectOption('BUY');
  await page.getByRole('button', { name: 'Apply filters' }).click();

  await expect(page).toHaveURL(/symbol=EURUSD/);
  await expect(page).toHaveURL(/action=BUY/);
  await expect(page.getByTestId('history-row')).toHaveCount(1);
  // The form is rebuilt from the URL, so the filters survive a reload.
  await page.reload();
  await expect(page.getByLabel('Symbol')).toHaveValue('EURUSD');
  await expect(page.getByLabel('Action')).toHaveValue('BUY');
  await expect(page.getByTestId('history-row')).toHaveCount(1);

  await page.getByRole('link', { name: 'Reset' }).click();
  await expect(page).toHaveURL(/\/analyses$/);
  await expect(page.getByTestId('history-row')).toHaveCount(3);
});

test('analyses min confidence hides weaker verdicts and an empty filter says so', async ({
  page,
}) => {
  await page.goto('/analyses?min_conf=70');
  await expect(page.getByTestId('history-row')).toHaveCount(1);

  await page.goto('/analyses?symbol=NOSUCH');
  await expect(page.getByTestId('history-empty')).toBeVisible();
});

test('a history row opens its detail page', async ({ page }) => {
  await page.goto('/analyses');
  await page.getByRole('link', { name: /XAUUSD/ }).click();

  await expect(page).toHaveURL(/\/analyses\/3$/);
  await expect(page.getByRole('heading', { level: 1 })).toContainText('XAUUSD');
  await expect(page.getByRole('heading', { name: 'Reasons' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Trade setup' })).toBeVisible();
});

test('an unknown or malformed analysis id shows the not-found page', async ({ page }) => {
  for (const id of ['999', 'abc']) {
    // notFound() streams after the loading shell, so the status is 200; assert the rendered page.
    await page.goto(`/analyses/${id}`);
    await expect(page.getByRole('heading', { name: 'Analysis not found' })).toBeVisible();
  }
});
