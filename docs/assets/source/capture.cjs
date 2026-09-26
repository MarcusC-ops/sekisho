/** Re-render presentation assets; requires an installed Playwright + Chromium.
 * CONSOLE_URL selects an already-running fixture console; omit to render artwork only.
 * Optional PLAYWRIGHT_MODULE and CHROMIUM_EXECUTABLE use an existing local toolchain.
 */
const path = require('node:path');
const fs = require('node:fs');
const { pathToFileURL } = require('node:url');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const root = path.resolve(__dirname, '../../..');
const out = path.join(root, 'docs/assets');
(async () => {
  const browser = await chromium.launch({ headless: true, ...(process.env.CHROMIUM_EXECUTABLE ? { executablePath: process.env.CHROMIUM_EXECUTABLE } : {}) });
  try {
    const page = await browser.newPage({ viewport: { width: 1280, height: 640 }, deviceScaleFactor: 1 });
    const artwork = pathToFileURL(path.join(__dirname, 'presentation.html')).href;
    for (const [hash, filename] of [['', 'banner.png'], ['#social', 'social-preview.png']]) {
      await page.goto(artwork + hash);
      await page.reload(); // Re-run the artwork script after a hash-only navigation.
      await page.evaluate(() => document.fonts.ready);
      await page.locator('#art').screenshot({ path: path.join(out, filename) });
      console.log('Rendered', filename);
    }
    if (process.env.CONSOLE_URL) {
      await page.setViewportSize({ width: 1440, height: 1000 });
      const cases = JSON.parse(fs.readFileSync(path.join(root, 'dashboard/fixtures/cases.json'), 'utf8'));
      const held = cases.find(c => c.verdict === 'HOLD' && c.trace?.taint_pct > 0 && c.status === 'HELD_ESCROWED');
      if (!held) throw new Error('No held mixer fixture found');
      for (const [route, filename, ready] of [
        ['/', 'console-decisions.png', 'Decision feed'],
        ['/cases/' + held.case_id, 'console-case.png', 'Decision timeline'],
        ['/treasury', 'console-treasury.png', 'Exposure by payee'],
      ]) {
        await page.goto(process.env.CONSOLE_URL.replace(/\/$/, '') + route);
        // Refuse to publish live or private data accidentally.
        await page.getByText('FIXTURE DATA', { exact: true }).waitFor();
        await page.getByRole('heading', { name: ready, exact: true }).waitFor();
        await page.evaluate(() => document.fonts.ready);
        await page.waitForTimeout(700);
        // Browser developer controls are not part of the product; all data remains intact.
        await page.addStyleTag({ content: 'nextjs-portal { display: none !important; }' });
        await page.screenshot({ path: path.join(out, filename), fullPage: false });
        console.log('Captured fixture console', route, filename);
      }
    }
  } finally { await browser.close(); }
})().catch(e => { console.error(e.message); process.exitCode = 1; });
