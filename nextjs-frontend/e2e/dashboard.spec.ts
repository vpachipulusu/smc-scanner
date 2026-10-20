import { expect, test } from './fixtures';

test('dashboard renders the scan summary and the latest verdicts', async ({ page }) => {
  await page.goto('/');

  await expect(page.getByRole('heading', { level: 1, name: 'Dashboard' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'TOUCHING now' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Latest scan summary' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Latest verdicts' })).toBeVisible();
  await expect(page.getByText('EURUSD', { exact: true }).first()).toBeVisible();
});

test('main navigation reaches the scan and analyses pages', async ({ page }) => {
  await page.goto('/');
  const nav = page.getByRole('navigation', { name: 'Main' });

  await nav.getByRole('link', { name: 'Scan' }).click();
  await expect(page).toHaveURL(/\/scan$/);
  await expect(page.getByRole('heading', { level: 1, name: 'Scan' })).toBeVisible();

  await nav.getByRole('link', { name: 'Analyses' }).click();
  await expect(page).toHaveURL(/\/analyses$/);
  await expect(page.getByRole('heading', { level: 1, name: 'Analyses' })).toBeVisible();
});
