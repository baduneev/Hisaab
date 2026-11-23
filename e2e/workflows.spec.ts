import { test, expect } from '@playwright/test';

test.afterEach(async ({page},info)=>{
  if(info.status!==info.expectedStatus){
    const invalid=await page.locator('.editor-form :invalid').evaluateAll(elements=>elements.map(element=>({tag:element.tagName,id:element.id,message:(element as HTMLInputElement).validationMessage})));
    await info.attach('invalid-fields',{body:JSON.stringify(invalid),contentType:'application/json'});
  }
});

test.beforeEach(async ({ page }) => {
  await page.goto('/');
  await page.getByLabel('Email address').fill('owner@hisaab.demo');
  await page.getByLabel('Password', { exact: true }).fill('Hisaab-demo-2026!');
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Business overview' })).toBeVisible();
});

test('owner can inspect collection evidence and create a contact', async ({ page }) => {
  await page.getByRole('link', { name: 'Contacts', exact: true }).click();
  await page.getByRole('button', { name: 'Add contact' }).click();
  const name = `Browser customer ${Date.now()}`;
  await page.getByLabel('Contact name').fill(name);
  await page.getByRole('button', { name: 'Save contact' }).click();
  await expect(page.getByText(name, { exact: true }).first()).toBeVisible();
  await page.getByText(name, { exact: true }).first().click();
  await expect(page.getByRole('heading', { name: 'Customer statement' })).toBeVisible();
});

test('bilingual navigation and mobile layout remain usable', async ({ page }) => {
  await page.getByRole('button', { name: 'नेपाली' }).click();
  await expect(page.getByRole('heading', { name: 'व्यवसायको अवस्था' })).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.locator('.sales-chart')).toBeVisible();
  await expect(page.locator('.collection-panel tbody tr').first()).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
  await page.getByRole('button', { name: 'Open navigation' }).click();
  await expect(page.getByRole('link', { name: 'बिक्री', exact: true })).toBeVisible();
});

test('invoice draft survives a reload and posts once', async ({ page }) => {
  await page.getByRole('link', { name: 'Sales', exact: true }).click();
  await page.getByRole('link', { name: 'New invoice', exact: true }).click();
  await page.getByLabel('Customer or supplier').selectOption({ label: 'Pokhara Mart' });
  await page.getByLabel('Product 1', { exact: true }).selectOption({ label: 'Basmati rice · 25 kg bag' });
  await page.getByLabel('Quantity 1').fill('1');
  await page.getByLabel('Notes').fill('Browser verified draft');
  await page.reload();
  await expect(page.getByLabel('Notes')).toHaveValue('Browser verified draft');
  await page.getByRole('button', { name: 'Save draft', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Post transaction', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Post transaction', exact: true }).click();
  await expect(page.getByText('Posted', { exact: true }).first()).toBeVisible();
  await expect(page.getByRole('link', { name: 'Download PDF' })).toBeVisible();
});

test('reports and AI explanations open supporting records', async ({ page }) => {
  await page.getByRole('link', { name: 'Reports', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Profit & loss', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Inventory valuation', exact: true }).click();
  await expect(page.getByText('Total inventory value', { exact: true })).toBeVisible();
  await page.getByRole('link', { name: /Insights/ }).click();
  await page.getByRole('button', { name: 'Which customers should I follow up with?' }).click();
  await expect(page.getByRole('heading', { name: 'What your records show' })).toBeVisible();
  await expect(page.locator('.evidence-links a').first()).toBeVisible();
});

test('offline drafts survive and financial posting waits for a connection', async ({ page, context }) => {
  await page.goto('/new/expense');
  await page.getByLabel('Notes').fill('Offline expense recovery');
  await context.setOffline(true);
  await expect(page.getByText(/You are offline/)).toBeVisible();
  await expect(page.getByRole('button', { name: 'Save draft', exact: true })).toBeDisabled();
  await context.setOffline(false);
  await page.reload();
  await expect(page.getByLabel('Notes')).toHaveValue('Offline expense recovery');
  await expect(page.getByRole('button', { name: 'Save draft', exact: true })).toBeEnabled();
});

test('capture desktop and mobile with no application crashes', async ({ page }, testInfo) => {
  const crashes: string[] = [];
  page.on('pageerror', error => crashes.push(error.message));
  await page.setViewportSize({ width: 1440, height: 1000 });
  await expect(page.locator('.sales-chart')).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath('overview-desktop.png'), fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  await page.screenshot({ path: testInfo.outputPath('overview-mobile.png'), fullPage: true });
  await page.getByRole('button', { name: 'नेपाली' }).click();
  await page.screenshot({ path: testInfo.outputPath('overview-nepali.png'), fullPage: true });
  expect(crashes).toEqual([]);
});

test('restored invoice waits for warehouse choices before it can be saved',async({page})=>{
  await page.goto('/new/sale');
  await page.getByLabel('Customer or supplier').selectOption({label:'Pokhara Mart'});
  await page.getByLabel('Product 1',{exact:true}).selectOption({label:'Basmati rice · 25 kg bag'});
  await page.getByLabel('Notes').fill('Slow warehouse restoration');
  await page.route('**/api/v1/warehouses',async route=>{await new Promise(resolve=>setTimeout(resolve,2000));await route.continue();});
  await page.reload();
  await expect(page.getByLabel('Notes')).toHaveValue('Slow warehouse restoration');
  await expect(page.getByRole('button',{name:'Save draft',exact:true})).toBeDisabled();
  await expect(page.getByRole('button',{name:'Save draft',exact:true})).toBeEnabled();
});
