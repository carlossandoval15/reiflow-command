// Nightly DealSauce pull. Run via nightly-pull.sh / launchd, never interactively
// with a password. Reuses the session saved by setup-login.js — if that session
// has expired, this exits with code 2 (NEED_LOGIN) and the wrapper script
// Telegrams Carlos instead of trying to log in itself.
//
// For each location in counties.json (round-robin, picking up where the last
// run left off), it: opens Property Search, selects the saved search
// "preforeclosures w auction", sets that one location, runs the search,
// switches to List view, selects all results, and exports CSV to ./incoming/.
// Stops once it's exported enough rows across locations (TARGET_ROWS) or hits
// MAX_LOCATIONS_PER_RUN, whichever comes first. Actual "new addresses" count
// is determined later by parse_import.py (dedup against what's already saved).

const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const DIR = __dirname;
const PROFILE_DIR = path.join(DIR, '.dealsauce-profile');
const INCOMING_DIR = path.join(DIR, 'incoming');
const LOG_DIR = path.join(DIR, 'logs');
const COUNTIES_FILE = path.join(DIR, 'counties.json');
const ROTATION_STATE_FILE = path.join(DIR, '.rotation-state.json');

const SAVED_SEARCH_NAME = 'preforeclosures w auction';
const TARGET_ROWS = 150;
const MAX_LOCATIONS_PER_RUN = 6;
const NAV_TIMEOUT = 45000;

function log(msg) {
  const line = `[${new Date().toISOString()}] ${msg}`;
  console.log(line);
}

function sanitize(s) {
  return s.replace(/[^a-z0-9]+/gi, '-').toLowerCase();
}

function loadJSON(file, fallback) {
  try { return JSON.parse(fs.readFileSync(file, 'utf8')); } catch (e) { return fallback; }
}

async function pullOneLocation(page, location, index) {
  await page.goto('https://beta.dealsauce.io/property-search', { waitUntil: 'domcontentloaded', timeout: NAV_TIMEOUT });
  await page.waitForTimeout(2500);

  if (page.url().includes('sign-in')) {
    throw new Error('NEED_LOGIN');
  }

  // 1. Open the filter panel (funnel icon — first icon button right of the
  //    main location search bar). Fall back to clicking near the search bar
  //    if a direct locator isn't found.
  const filterCandidates = [
    page.locator('header button, [class*="toolbar"] button').filter({ hasText: '' }),
  ];
  // Prefer clicking by proximity to the search placeholder, which is stable text.
  const searchBar = page.getByPlaceholder(/Search by Address, City, County, State, Zip Code/i).first();
  await searchBar.waitFor({ state: 'visible', timeout: 20000 });
  const box = await searchBar.boundingBox();
  if (!box) throw new Error('Could not locate the main search bar');
  // The filter (funnel) icon sits a fixed offset to the right of the search bar.
  await page.mouse.click(box.x + box.width + 45, box.y + box.height / 2);
  await page.waitForTimeout(1000);

  // 2. Saved Search dropdown -> pick our saved search
  const savedSearchLabel = page.getByText('Saved Search', { exact: false }).first();
  await savedSearchLabel.click({ timeout: 15000 });
  await page.waitForTimeout(500);
  await page.getByText(SAVED_SEARCH_NAME, { exact: false }).first().click({ timeout: 15000 });
  await page.waitForTimeout(800);

  // 3. Set location for this run
  const locInput = page.getByPlaceholder(/Search by Address, City, County, State, Zip Code/i).first();
  await locInput.click();
  await locInput.fill(location);
  await page.waitForTimeout(1200);
  await page.getByText('+ ADD', { exact: false }).first().click({ timeout: 15000 });
  await page.waitForTimeout(1000);

  // 4. Run Search
  const runBtn = page.getByRole('button', { name: /Run Search/i }).first();
  await runBtn.click({ timeout: 15000 });
  await page.waitForTimeout(2500);

  // 5. Switch to LIST view
  await page.getByText('LIST', { exact: true }).first().click({ timeout: 15000 });
  await page.waitForTimeout(2000);

  // Read "Properties Found: N"
  let found = 0;
  try {
    const txt = await page.getByText(/Properties Found/i).first().locator('..').textContent();
    const m = (txt || '').match(/(\d[\d,]*)/);
    if (m) found = parseInt(m[1].replace(/,/g, ''), 10);
  } catch (e) { /* best-effort */ }

  if (found === 0) {
    log(`  ${location}: 0 properties found, skipping export`);
    return { rows: 0, file: null };
  }

  // 6. Select all (header checkbox)
  const headerCheckbox = page.locator('thead input[type="checkbox"], thead [role="checkbox"]').first();
  await headerCheckbox.click({ timeout: 15000 });
  await page.waitForTimeout(800);

  // 7. Download -> Next: Columns -> Download N (CSV)
  await page.getByText('Download', { exact: true }).first().click({ timeout: 15000 });
  await page.waitForTimeout(1000);
  await page.getByText(/Next:\s*Columns/i).first().click({ timeout: 15000 });
  await page.waitForTimeout(800);

  const [download] = await Promise.all([
    page.waitForEvent('download', { timeout: 30000 }),
    page.getByText(/Download\s+\d+\s*\(CSV\)/i).first().click(),
  ]);
  const suggested = download.suggestedFilename() || `export-${Date.now()}.csv`;
  const destPath = path.join(INCOMING_DIR, `${Date.now()}-${sanitize(location)}-${suggested}`);
  await download.saveAs(destPath);
  log(`  ${location}: exported ${found} rows -> ${path.basename(destPath)}`);
  return { rows: found, file: destPath };
}

async function main() {
  fs.mkdirSync(INCOMING_DIR, { recursive: true });
  fs.mkdirSync(LOG_DIR, { recursive: true });

  const countiesCfg = loadJSON(COUNTIES_FILE, { locations: [] });
  const locations = countiesCfg.locations || [];
  if (locations.length === 0) {
    log('No locations configured in counties.json — nothing to do.');
    process.exit(1);
  }

  const state = loadJSON(ROTATION_STATE_FILE, { nextIndex: 0 });
  let idx = state.nextIndex || 0;

  const context = await chromium.launchPersistentContext(PROFILE_DIR, {
    headless: true,
    viewport: { width: 1400, height: 900 },
    acceptDownloads: true,
  });
  const page = context.pages()[0] || (await context.newPage());
  page.setDefaultTimeout(20000);

  let totalRows = 0;
  let locationsTried = 0;
  const exportedFiles = [];
  const errors = [];

  try {
    while (totalRows < TARGET_ROWS && locationsTried < MAX_LOCATIONS_PER_RUN && locationsTried < locations.length) {
      const location = locations[idx % locations.length];
      idx += 1;
      locationsTried += 1;
      try {
        const result = await pullOneLocation(page, location, locationsTried);
        totalRows += result.rows;
        if (result.file) exportedFiles.push(result.file);
      } catch (e) {
        if (e.message === 'NEED_LOGIN') {
          await context.close();
          console.log('NEED_LOGIN');
          process.exit(2);
        }
        log(`  ${location}: FAILED — ${e.message}`);
        errors.push(`${location}: ${e.message}`);
        try {
          const shotPath = path.join(LOG_DIR, `error-${Date.now()}-${sanitize(location)}.png`);
          await page.screenshot({ path: shotPath, fullPage: false });
        } catch (e2) { /* ignore */ }
      }
    }
  } finally {
    fs.writeFileSync(ROTATION_STATE_FILE, JSON.stringify({ nextIndex: idx }, null, 2));
    await context.close();
  }

  const summary = { totalRows, locationsTried, exportedFiles, errors };
  console.log('SUMMARY_JSON:' + JSON.stringify(summary));
  process.exit(errors.length > 0 && exportedFiles.length === 0 ? 1 : 0);
}

main().catch((e) => {
  console.error('FATAL:', e);
  process.exit(1);
});
