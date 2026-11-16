/**
 * The product journeys from the redesign brief (docs/UX_QA_AUDIT.md, docs/TESTING.md), against the real
 * running stack: real OTP through the dev SMS outbox, real fields in the development database, real API
 * answers. One new test user per run; the journeys depend on each other, so they run in order.
 */
import { expect, test, type BrowserContext, type Page } from '@playwright/test';
import { chooseFromCombobox, expectNoHorizontalOverflow, mapBox, signIn, testPhone } from './helpers';

test.describe.configure({ mode: 'serial' });

const phone = testPhone();
const first = `E2E grape plot ${phone.slice(-4)}`;
const second = `E2E cotton plot ${phone.slice(-4)}`;
let context: BrowserContext;
let page: Page;

test.beforeAll(async ({ browser }) => {
  context = await browser.newContext();
  page = await context.newPage();
});
test.afterAll(async () => { await context.close(); });

async function addField(name: string, crop: RegExp, district: string, taluka: string) {
  await expect(page.getByRole('heading', { level: 1, name: 'Where is your farm?' })).toBeVisible();
  // The map is optional: nothing map-related is loaded until it is asked for.
  await expect(page.locator('.maplibregl-map')).toHaveCount(0);
  await chooseFromCombobox(page, 'District', district);
  await chooseFromCombobox(page, 'Taluka', taluka);
  const village = page.getByRole('combobox', { name: 'Village' });
  await expect(village).toBeEnabled({ timeout: 20_000 });
  await village.click();
  await page.getByRole('option').first().click();
  await expect(page.getByText('Village centre')).toBeVisible();
  await page.getByRole('button', { name: 'Continue to Crop' }).click();

  await expect(page.getByRole('heading', { level: 1, name: 'What do you grow here?' })).toBeVisible();
  await page.getByRole('button', { name: 'Continue to Details' }).click();
  await expect(page.getByText('Choose a crop to continue.')).toBeVisible(); // validation before moving on
  await page.getByRole('radio', { name: crop }).click();
  await page.locator('input[type="date"]').fill('2026-07-01');
  await page.getByRole('button', { name: 'Continue to Details' }).click();

  await expect(page.getByRole('heading', { level: 1, name: 'Farm details' })).toBeVisible();
  await page.getByLabel('Field name (optional)').fill(name);
  await page.getByLabel('Area (optional)').fill('1.5');
  // Back and forward keep what was entered.
  await page.getByRole('button', { name: 'Back', exact: true }).click();
  await expect(page.getByRole('radio', { name: crop })).toHaveAttribute('aria-checked', 'true');
  await page.getByRole('button', { name: 'Continue to Details' }).click();
  await expect(page.getByLabel('Field name (optional)')).toHaveValue(name);
  await page.getByRole('button', { name: 'Continue to Review' }).click();

  await expect(page.getByRole('heading', { level: 1, name: 'Review and save' })).toBeVisible();
  await expect(page.getByText(name)).toBeVisible();
  await expect(page.getByText(new RegExp(`${taluka}, ${district}`))).toBeVisible();
  await page.getByRole('button', { name: 'Save field' }).click();
}

test('Journey 1: a first-time user goes landing, sign in, onboarding, Home', async () => {
  await page.goto('/?lang=en');
  await expect(page.getByRole('heading', { level: 1, name: 'Know what to do on your farm today' })).toBeVisible();
  await expect(page.locator('.maplibregl-map')).toHaveCount(0); // the landing page is not the map
  // LAND-03: the landing page only leads to sign in; nothing on it opens the app without an account.
  const header = page.getByRole('banner');
  await expect(header.getByRole('link', { name: 'Sign in', exact: true })).toBeVisible();
  await expect(page.getByRole('link', { name: /Open my dashboard/ })).toHaveCount(0);
  await expect(page.getByRole('link', { name: /Regional outlook|Open the map|outlook map/i })).toHaveCount(0);
  await expect(page.getByText("Sign in to open the full outlook with each district's details.")).toBeVisible();
  for (const path of ['/en/map', '/en/ask', '/en/ask/1']) {
    await page.goto(path);
    await expect(page, `${path} needs sign in`).toHaveURL(/\/en\/signin\?next=/);
  }
  await page.goto('/?lang=en');
  await page.getByRole('link', { name: 'Get started' }).first().click();
  await expect(page).toHaveURL(/\/en\/signin$/);
  await expect(page.getByRole('heading', { level: 1, name: 'Sign in or create an account' })).toBeVisible();

  await signIn(page, phone);
  // New number: the language step, then onboarding.
  await expect(page.getByRole('heading', { name: 'Choose your language' })).toBeVisible();
  await page.getByRole('radio', { name: /English/ }).check();
  await page.getByRole('button', { name: 'Continue' }).click();
  await expect(page).toHaveURL(/\/en\/onboarding$/);
  await expect(page.getByText('Step 1 of 4')).toBeVisible();

  await addField(first, /Grape/, 'Nashik', 'Niphad');
  await expect(page).toHaveURL(/\/en\/home$/);
  await expect(page.getByRole('heading', { level: 1, name: 'Today on your farm' })).toBeVisible();
  await expect(page.getByText(first).first()).toBeVisible();
});

test('Journey 3: add another field from My Fields; both remain', async () => {
  await page.getByRole('navigation', { name: 'Main' }).getByRole('link', { name: 'Fields', exact: true }).click();
  await expect(page).toHaveURL(/\/en\/fields$/);
  await page.getByRole('link', { name: 'Add field' }).first().click();
  await expect(page).toHaveURL(/\/en\/fields\/new$/);
  await expect(page.getByText('Add a field')).toBeVisible();
  await addField(second, /Cotton/, 'Pune', 'Baramati');
  await expect(page).toHaveURL(/\/en\/fields\?added=\d+$/);
  await expect(page.getByText("Checking today's status")).toHaveCount(0); // today's status has streamed in
  await expect(page.getByText(/Field saved\. Its first decision/).filter({ visible: true }).first()).toBeVisible();
  await expect(page.getByRole('main').getByRole('link', { name: first, exact: true })).toBeVisible();
  await expect(page.getByRole('main').getByRole('link', { name: second, exact: true })).toBeVisible();
  // Search and filter on My Fields.
  await page.getByPlaceholder('Search by name, crop or village').fill('cotton');
  await expect(page.getByRole('main').getByRole('link', { name: second, exact: true })).toBeVisible();
  await expect(page.getByRole('main').getByRole('link', { name: first, exact: true })).toHaveCount(0);
  await page.getByPlaceholder('Search by name, crop or village').fill('');
});

test('Journey 4: every destination from the desktop nav, active state, back, refresh, direct URL', async () => {
  const nav = page.getByRole('navigation', { name: 'Main' });
  const stops: [string, RegExp, string][] = [
    ['Home', /\/en\/home$/, 'Today on your farm'],
    ['Fields', /\/en\/fields$/, 'My fields'],
    ['Ask assistant', /\/en\/ask$/, 'New conversation'],
    ['Market', /\/en\/market$/, 'Market'],
    ['Alerts', /\/en\/alert$/, 'Alerts'],
    ['Regional outlook', /\/en\/map$/, 'Regional outlook'],
  ];
  for (const [label, url, h1] of stops) {
    await nav.getByRole('link', { name: label, exact: true }).click();
    await expect(page).toHaveURL(url);
    await expect(page.getByRole('heading', { level: 1, name: h1, exact: true })).toBeVisible({ timeout: 30_000 });
    await expect(nav.getByRole('link', { name: label, exact: true })).toHaveAttribute('aria-current', 'page');
    await expectNoHorizontalOverflow(page, label);
  }
  await page.goBack();
  await expect(page).toHaveURL(/\/en\/alert$/);
  await page.reload();
  await expect(page.getByRole('heading', { level: 1, name: 'Alerts', exact: true })).toBeVisible();
  await nav.getByRole('link', { name: 'Settings' }).click();
  await expect(page.getByRole('heading', { level: 1, name: 'Settings' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Delete account' })).toHaveCount(0); // no control that cannot work
  // A field detail page belongs to My Fields in the nav.
  await page.goto('/en/fields');
  await page.getByRole('main').getByRole('link', { name: first, exact: true }).click();
  await expect(page.getByRole('heading', { level: 1, name: first })).toBeVisible();
  await expect(nav.getByRole('link', { name: 'Fields', exact: true })).toHaveAttribute('aria-current', 'page');
  await expect(page.getByRole('link', { name: 'My fields' }).first()).toBeVisible();

  // Mobile: five tabs at the bottom, the rest in More.
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/en/home');
  const tabs = page.getByRole('navigation', { name: 'Main' });
  for (const label of ['Home', 'Fields', 'Ask', 'Market', 'Alerts']) await expect(tabs.getByRole('link', { name: new RegExp(`^${label}`) })).toBeVisible();
  await tabs.getByRole('link', { name: 'Market' }).click();
  await expect(page).toHaveURL(/\/en\/market$/);
  await expect(tabs.getByRole('link', { name: 'Market' })).toHaveAttribute('aria-current', 'page');
  await page.getByRole('button', { name: 'More' }).click();
  const more = page.getByRole('dialog', { name: 'More' });
  await expect(more.getByRole('link', { name: 'Regional outlook' })).toBeVisible();
  await more.getByRole('link', { name: 'Regional outlook' }).click();
  await expect(page).toHaveURL(/\/en\/map$/);
  await expectNoHorizontalOverflow(page, 'mobile map');
  await page.setViewportSize({ width: 1280, height: 800 });
});

test('Journey 5: Regional outlook map, district list and details never resize the map', async () => {
  for (const size of [{ width: 1280, height: 800 }, { width: 1440, height: 900 }, { width: 390, height: 844 }]) {
    await page.setViewportSize(size);
    await page.goto('/en/map');
    await expect(page.locator('[data-testid="map-box"] canvas, [data-testid="map-box"] svg').first()).toBeVisible({ timeout: 30_000 });
    const before = await mapBox(page);
    expect(before.height).toBeGreaterThan(250);
    const rows = page.locator('ul li button[aria-pressed]');
    await rows.first().click();
    await expect(page.getByRole('button', { name: 'Close district details' })).toBeVisible();
    await page.getByRole('button', { name: 'Close district details' }).click();
    await page.getByRole('button', { name: /Show all 36 districts/ }).click();
    await expect(rows).toHaveCount(36);
    const expanded = await mapBox(page);
    expect(Math.abs(expanded.height - before.height), `map height changed at ${size.width}px`).toBeLessThan(2);
    expect(Math.abs(expanded.width - before.width), `map width changed at ${size.width}px`).toBeLessThan(2);
    await page.getByPlaceholder('Search districts').fill('pune');
    await expect(rows).toHaveCount(1);
    await expect(rows.first()).toContainText('Pune');
    await page.getByPlaceholder('Search districts').fill('');
    await page.getByLabel('Risk level').selectOption('none');
    await rows.nth(1).click();
    await expect(page.getByRole('button', { name: 'Close district details' })).toBeVisible();
    await page.getByLabel('Risk level').selectOption('all');
    await page.getByRole('button', { name: 'Show fewer' }).click();
    await expect(rows).toHaveCount(10);
    const after = await mapBox(page);
    if (size.width >= 1440) expect(Math.abs(after.height - before.height)).toBeLessThan(2);
    await expect(page.getByRole('link', { name: 'District boundaries: geoBoundaries' })).toBeVisible(); // attribution stays visible
    await expectNoHorizontalOverflow(page, `map ${size.width}`);
  }
  await page.setViewportSize({ width: 1280, height: 800 });
});

test('Journey 6: the assistant answers the question that was asked; Stop keeps nothing; history', async () => {
  await page.goto('/en/ask');
  await expect(page.getByRole('heading', { level: 1, name: 'New conversation' })).toBeVisible();
  await expect(page.getByText('Spoken questions are not available on this server yet. Type your question below.')).toBeVisible();
  const main = page.getByRole('main');
  const box = page.getByLabel('Your question');
  const answers = main.locator('[class*="aiRow"]');
  const ask = async (q: string) => {
    const before = await answers.count();
    await box.fill(q);
    await page.getByRole('button', { name: 'Send question' }).click();
    await expect(page.getByRole('button', { name: 'Stop answer' })).toHaveCount(0, { timeout: 60_000 });
    const row = answers.nth(before);
    await expect(row.getByRole('button', { name: 'Copy' })).toBeVisible(); // a finished answer, not an error
    return row;
  };
  // A suggestion fills the box and waits for Send.
  await main.getByRole('list', { name: 'Try asking' }).getByRole('button').first().click();
  await expect(box).not.toHaveValue('');
  await expect(answers).toHaveCount(0);

  await page.getByRole('combobox', { name: 'Field' }).selectOption({ label: second });
  const rain = await ask('Will heavy rain come to my cotton field?');
  await expect(rain).toContainText(/heavy rain/i);
  await expect(rain).not.toContainText('°C');
  await expect(rain).not.toContainText('No weather risk');
  // The first answer gives the conversation its own address and puts it in the history.
  await expect(page).toHaveURL(/\/en\/ask\/\d+$/);
  const threadUrl = page.url();
  const history = page.getByRole('navigation', { name: 'Conversations' });
  await expect(history.getByRole('link', { name: 'Will heavy rain come to my cotton field?' })).toBeVisible();
  await expect(history.getByRole('heading', { name: 'Today' })).toBeVisible();

  // ASK-09: Stop while the answer is being worked out. Nothing is kept, and the question can be edited.
  await box.fill('Should I spray for mealybug on cotton this week?');
  await page.getByRole('button', { name: 'Send question' }).click();
  await page.getByRole('button', { name: 'Stop answer' }).click();
  await expect(main.getByText('Stopped. This question was not saved.')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Send question' })).toBeVisible();
  await page.getByRole('button', { name: 'Edit question' }).click();
  await expect(box).toHaveValue('Should I spray for mealybug on cotton this week?');
  await expect(main.getByText('Stopped. This question was not saved.')).toHaveCount(0);
  // Esc stops too.
  await page.getByRole('button', { name: 'Send question' }).click();
  await expect(page.getByRole('button', { name: 'Stop answer' })).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(main.getByText('Stopped. This question was not saved.')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Ask again' })).toBeVisible();

  const off = await ask('Who won the cricket match yesterday?');
  await expect(off).toContainText('I can only help with farming');
  // ASK-10: a question about the field itself is answered from the saved field, never refused as off-topic.
  const mine = await ask('What crop am I growing here?');
  await expect(mine).not.toContainText('I can only help with farming');
  // Worded by the model when one is configured, by the field summary otherwise: either way the field and its crop.
  await expect(mine).toContainText(second);
  await expect(mine).toContainText(/cotton/i);
  const help = await ask('Help me');
  await expect(help).not.toContainText('I can only help with farming');
  await expect(help).toContainText('cotton');
  const frost = await ask('Is there frost risk for my cotton?');
  await expect(frost).toContainText(/frost|Frost/);
  await expect(frost).not.toContainText(/heavy rain/i);
  const pest = await ask('Which pests attack cotton bolls?');
  await expect(pest).not.toContainText('lowest temperature');
  await expect(pest).not.toContainText('highest temperature');
  await expect(page).toHaveURL(threadUrl); // the same conversation throughout

  // Give the stopped requests time to finish on the server, then reload: they were never kept.
  await page.waitForTimeout(15_000);
  await page.goto(threadUrl);
  await expect(page.getByRole('heading', { level: 1, name: 'Will heavy rain come to my cotton field?' })).toBeVisible();
  for (const q of ['Will heavy rain come to my cotton field?', 'Who won the cricket match yesterday?', 'What crop am I growing here?', 'Help me', 'Is there frost risk for my cotton?', 'Which pests attack cotton bolls?']) {
    await expect(main.locator('[class*="userBubble"]', { hasText: q })).toHaveCount(1);
  }
  await expect(main.getByText('Should I spray for mealybug on cotton this week?')).toHaveCount(0);
  await expect(answers).toHaveCount(6);

  // A new conversation, then back to the old one from the history.
  await history.getByRole('link', { name: 'New conversation' }).click();
  await expect(page).toHaveURL(/\/en\/ask$/);
  await expect(page.getByRole('heading', { level: 1, name: 'New conversation' })).toBeVisible();
  await expect(answers).toHaveCount(0);
  await history.getByRole('link', { name: 'Will heavy rain come to my cotton field?' }).click();
  await expect(page).toHaveURL(threadUrl);
  await expect(answers).toHaveCount(6);

  // Search finds it by what was said inside, not only by its title.
  await history.getByRole('searchbox', { name: 'Search conversations' }).fill('cricket');
  await expect(history.getByRole('link', { name: 'Will heavy rain come to my cotton field?' })).toBeVisible();
  await history.getByRole('searchbox', { name: 'Search conversations' }).fill('zzzz no such words');
  await expect(history.getByText('Nothing matches zzzz no such words.')).toBeVisible();
  await history.getByRole('searchbox', { name: 'Search conversations' }).fill('');

  // Rename and save to the top; both survive a reload.
  await history.getByRole('button', { name: 'More for Will heavy rain come to my cotton field?' }).click();
  await page.getByRole('menuitem', { name: 'Rename' }).click();
  await history.getByLabel('Conversation name').fill('Cotton questions');
  await history.getByLabel('Conversation name').press('Enter');
  await expect(history.getByRole('link', { name: 'Cotton questions' })).toBeVisible();
  await history.getByRole('button', { name: 'More for Cotton questions' }).click();
  await page.getByRole('menuitem', { name: 'Save to top' }).click();
  await expect(history.getByRole('heading', { name: 'Saved' })).toBeVisible();
  await page.reload();
  await expect(page.getByRole('heading', { level: 1, name: 'Cotton questions' })).toBeVisible();
  await expect(history.getByRole('heading', { name: 'Saved' })).toBeVisible();

  // Phones: the history opens as a sheet from the conversation header.
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole('button', { name: 'Conversations' }).click();
  const sheet = page.getByRole('dialog', { name: 'Conversations' });
  await expect(sheet.getByRole('link', { name: 'Cotton questions' })).toBeVisible();
  await sheet.getByRole('link', { name: 'New conversation' }).click();
  await expect(page.getByRole('heading', { level: 1, name: 'New conversation' })).toBeVisible();
  await expect(sheet).toBeHidden();
  await expectNoHorizontalOverflow(page, 'mobile ask');
  await page.setViewportSize({ width: 1280, height: 800 });

  // Delete asks first, then removes it everywhere.
  await page.goto(threadUrl);
  await history.getByRole('button', { name: 'More for Cotton questions' }).click();
  await page.getByRole('menuitem', { name: 'Delete' }).click();
  const confirm = page.getByRole('dialog', { name: 'Delete this conversation?' });
  await expect(confirm).toContainText('cannot be undone');
  await confirm.getByRole('button', { name: 'Delete' }).click();
  await expect(page.getByText('Conversation deleted')).toBeVisible();
  await expect(page).toHaveURL(/\/en\/ask$/);
  await expect(history.getByRole('link', { name: 'Cotton questions' })).toHaveCount(0);
  // The page streams, so the status is already sent; the not-found page is what is shown.
  await page.goto(threadUrl);
  await expect(page.getByRole('heading', { level: 1, name: 'This page does not exist' })).toBeVisible();
});

test('Journey 7: unavailable data is explained, never invented', async () => {
  await page.goto('/en/market');
  await expect(page.getByText(/Mandi prices are not connected|No prices for/)).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText('No chart, forecast or recommendation is shown without real prices.')).toBeVisible();
  await page.goto('/en/home');
  await expect(page.getByText(/No mandi price is available for this crop|Modal price at/)).toBeVisible();
  // The road panel streams in after its own network lookups; it either estimates or says why it cannot.
  await expect(page.getByText(/Estimated from rainfall and terrain|route from this field to a mandi is not known|Route risk is unavailable/).first()).toBeVisible({ timeout: 45_000 });
  // The assistant API failing: the question is kept with a retry, not answered with something made up.
  await page.route('**/api/proxy/ask', (r) => r.fulfill({ status: 500, contentType: 'application/json', body: JSON.stringify({ error: { code: 'internal_error', message: 'x', details: {}, trace_id: 'e2e' } }) }));
  await page.goto('/en/ask');
  await page.getByLabel('Your question').fill('Is there frost risk for my grape?');
  await page.getByRole('button', { name: 'Send question' }).click();
  await expect(page.getByText('Something went wrong while answering. Please ask again.')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Ask again' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Edit question' })).toBeVisible();
  await page.unroute('**/api/proxy/ask');
});

test('Responsive: no horizontal overflow on any page at the required sizes', async () => {
  const sizes = [[360, 800], [390, 844], [430, 932], [768, 1024], [1024, 768], [1280, 800], [1440, 900], [1920, 1080]] as const;
  const paths = ['/?lang=en', '/?lang=mr', '/mr/home', '/hi/map', '/en/home', '/en/fields', '/en/fields/new', '/en/ask', '/en/market', '/en/alert', '/en/settings', '/en/settings/calibration', '/en/map'];
  await page.goto('/en/fields');
  const fieldHref = await page.getByRole('main').getByRole('link', { name: first, exact: true }).getAttribute('href');
  if (fieldHref) paths.push(fieldHref);
  for (const [width, height] of sizes) {
    await page.setViewportSize({ width, height });
    for (const p of paths) {
      await page.goto(p);
      await expect(page.locator('h1').first()).toBeVisible();
      await expectNoHorizontalOverflow(page, `${p} at ${width}x${height}`);
    }
  }
  await page.setViewportSize({ width: 1280, height: 800 });
});

test('Languages: Marathi and Hindi pages render in their language', async () => {
  await page.goto('/mr/home');
  await expect(page.getByRole('heading', { level: 1, name: 'आज तुमच्या शेतात' })).toBeVisible();
  await expect(page.locator('html')).toHaveAttribute('lang', 'mr');
  await page.goto('/hi/fields');
  await expect(page.getByRole('heading', { level: 1, name: 'मेरे खेत' })).toBeVisible();
  await page.goto('/?lang=mr');
  await expect(page.getByRole('heading', { level: 1, name: 'आज शेतात काय करायचे ते जाणून घ्या' })).toBeVisible();
  await page.goto('/en/home');
});

test('Delete a field with confirmation', async () => {
  await page.goto('/en/fields');
  await expect(page.getByText("Checking today's status")).toHaveCount(0);
  await page.getByRole('button', { name: `Delete: ${second}` }).click();
  const dialog = page.getByRole('dialog', { name: `Delete ${second}?` });
  await expect(dialog).toBeVisible();
  await dialog.getByRole('button', { name: 'Cancel' }).click();
  await expect(page.getByRole('main').getByRole('link', { name: second, exact: true })).toBeVisible();
  await page.getByRole('button', { name: `Delete: ${second}` }).click();
  await page.getByRole('dialog', { name: `Delete ${second}?` }).getByRole('button', { name: 'Delete field' }).click();
  await expect(page.getByRole('main').getByRole('link', { name: second, exact: true })).toHaveCount(0);
  await expect(page.getByRole('main').getByRole('link', { name: first, exact: true })).toBeVisible();
});

test('Journey 2: sign out, then a returning user goes straight to Home', async () => {
  await page.goto('/en/settings');
  await page.getByRole('button', { name: 'Sign out' }).first().click();
  await expect(page).toHaveURL(/\/en\/signin/);
  // Protected pages now need sign-in again, and keep where you were going.
  await page.goto('/en/fields');
  await expect(page).toHaveURL(/\/en\/signin\?next=%2Fen%2Ffields/);
  await page.goto('/?lang=en');
  await expect(page.getByRole('link', { name: 'Get started' }).first()).toBeVisible();
  await page.getByRole('link', { name: 'Get started' }).first().click();
  await signIn(page, phone);
  await expect(page).toHaveURL(/\/en\/home$/, { timeout: 30_000 });
  await expect(page.getByText(first).first()).toBeVisible();
  // Onboarding is never repeated for a user with fields.
  await page.goto('/en/onboarding');
  await expect(page).toHaveURL(/\/en\/fields\/new$/);
  await expect(page.getByText('Add a field')).toBeVisible();
});
