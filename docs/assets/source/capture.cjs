/** Re-render brand and presentation assets; requires an installed Playwright + Chromium.
 * CONSOLE_URL selects an already-running fixture console; omit to render artwork only.
 * Optional PLAYWRIGHT_MODULE and CHROMIUM_EXECUTABLE use an existing local toolchain.
 */
const path = require('node:path');
const fs = require('node:fs');
const { pathToFileURL } = require('node:url');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const root = path.resolve(__dirname, '../../..');
const out = path.join(root, 'docs/assets');
const site = path.join(root, 'website');
const source = name => pathToFileURL(path.join(__dirname, name)).href;

// ICO container holding PNG images (supported by every current browser).
function writeIco(file, pngs) {
  const header = Buffer.alloc(6 + 16 * pngs.length);
  header.writeUInt16LE(1, 2);
  header.writeUInt16LE(pngs.length, 4);
  let offset = header.length;
  pngs.forEach(({ size, data }, i) => {
    const entry = 6 + 16 * i;
    header.writeUInt8(size % 256, entry);
    header.writeUInt8(size % 256, entry + 1);
    header.writeUInt16LE(1, entry + 4);
    header.writeUInt16LE(32, entry + 6);
    header.writeUInt32LE(data.length, entry + 8);
    header.writeUInt32LE(offset, entry + 12);
    offset += data.length;
  });
  fs.writeFileSync(file, Buffer.concat([header, ...pngs.map(p => p.data)]));
}

(async () => {
  const browser = await chromium.launch({ headless: true, ...(process.env.CHROMIUM_EXECUTABLE ? { executablePath: process.env.CHROMIUM_EXECUTABLE } : {}) });
  try {
    const page = await browser.newPage({ viewport: { width: 1280, height: 640 }, deviceScaleFactor: 1 });
    const render = async (url, file, options = {}) => {
      await page.goto(url);
      await page.reload(); // Re-run the artwork script after a hash-only navigation.
      await page.evaluate(() => document.fonts.ready);
      const data = await page.locator('#art').screenshot({ omitBackground: true, ...options });
      if (file) { fs.writeFileSync(file, data); console.log('Rendered', path.relative(root, file)); }
      return data;
    };

    // Earlier navy presentation banner, retained for decks that already use it.
    await render(source('presentation.html'), path.join(out, 'banner.png'));
    // Current editorial identity: repository preview and website Open Graph cards.
    await render(source('social.html') + '#github', path.join(out, 'social-preview.png'));
    await render(source('social.html') + '#home', path.join(site, 'assets/og-home.png'));
    await render(source('social.html') + '#try', path.join(site, 'assets/og-try.png'));

    const icon = (variant, size, file) => render(`${source('brand.html')}?size=${size}#${variant}`, file);
    const ico = [];
    for (const size of [16, 32, 48]) ico.push({ size, data: await icon('icon', size) });
    writeIco(path.join(site, 'favicon.ico'), ico);
    console.log('Rendered website/favicon.ico');
    await icon('full', 180, path.join(site, 'apple-touch-icon.png'));
    await icon('icon', 192, path.join(site, 'assets/icon-192.png'));
    await icon('icon', 512, path.join(site, 'assets/icon-512.png'));
    await icon('maskable', 512, path.join(site, 'assets/icon-maskable-512.png'));
    await icon('icon', 1024, path.join(out, 'logo-1024.png'));
    await page.close();

    const hiDpi = await browser.newPage({ viewport: { width: 800, height: 200 }, deviceScaleFactor: 4 });
    for (const variant of ['lockup', 'lockup-dark']) {
      await hiDpi.goto(`${source('brand.html')}#${variant}`);
      await hiDpi.reload(); // Hash-only navigation does not re-run the artwork script.
      await hiDpi.evaluate(() => document.fonts.ready);
      await hiDpi.locator('#art').screenshot({ path: path.join(out, `${variant}.png`), omitBackground: true });
      console.log(`Rendered docs/assets/${variant}.png`);
    }
    await hiDpi.close();

    if (process.env.CONSOLE_URL) {
      const console_ = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
      const cases = JSON.parse(fs.readFileSync(path.join(root, 'dashboard/fixtures/cases.json'), 'utf8'));
      const held = cases.find(c => c.verdict === 'HOLD' && c.trace?.taint_pct > 0 && c.status === 'HELD_ESCROWED');
      if (!held) throw new Error('No held mixer fixture found');
      for (const [route, filename, ready] of [
        ['/', 'console-decisions.jpg', 'Decision feed'],
        ['/cases/' + held.case_id, 'console-case.jpg', 'Decision timeline'],
        ['/treasury', 'console-treasury.png', 'Exposure by payee'],
      ]) {
        await console_.goto(process.env.CONSOLE_URL.replace(/\/$/, '') + route);
        // Refuse to publish live or private data accidentally.
        await console_.getByText('FIXTURE DATA', { exact: true }).waitFor();
        await console_.getByRole('heading', { name: ready, exact: true }).waitFor();
        await console_.evaluate(() => document.fonts.ready);
        await console_.waitForTimeout(700);
        // Browser developer controls are not part of the product; all data remains intact.
        await console_.addStyleTag({ content: 'nextjs-portal { display: none !important; }' });
        await console_.screenshot({ path: path.join(out, filename), fullPage: false, ...(filename.endsWith('.jpg') ? { quality: 85 } : {}) });
        console.log('Captured fixture console', route, filename);
      }
    }
  } finally { await browser.close(); }
})().catch(e => { console.error(e.message); process.exitCode = 1; });
