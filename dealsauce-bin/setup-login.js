// One-time interactive login. Run this yourself from a terminal:
//   node setup-login.js
// A real Chrome window opens to DealSauce sign-in. Log in yourself (Clerk auth) —
// this script never sees or touches your password. Once you land on
// /property-search, come back to the terminal and press Enter; the session
// (cookies) gets saved to PROFILE_DIR so nightly-pull.js can reuse it without
// ever logging in again.
const { chromium } = require('playwright');
const path = require('path');
const readline = require('readline');

const PROFILE_DIR = path.join(__dirname, '.dealsauce-profile');

(async () => {
  console.log('Opening Chrome — log into DealSauce (beta.dealsauce.io) yourself.');
  console.log('This script will NOT type your password. Waiting for you...\n');

  const context = await chromium.launchPersistentContext(PROFILE_DIR, {
    headless: false,
    viewport: { width: 1400, height: 900 },
  });
  const page = context.pages()[0] || (await context.newPage());
  await page.goto('https://beta.dealsauce.io/sign-in');

  const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
  await new Promise((resolve) => {
    rl.question('\nOnce you are logged in and see the property search page, press Enter here...\n', () => {
      rl.close();
      resolve();
    });
  });

  const url = page.url();
  if (url.includes('sign-in')) {
    console.log('\n⚠️  Still on the sign-in page — login may not have completed. Session saved anyway, but re-run this script if the nightly pull fails.');
  } else {
    console.log(`\n✅ Logged in (landed on ${url}). Session saved to ${PROFILE_DIR}.`);
  }

  await context.close();
  process.exit(0);
})();
