// Browser check for the explainer, run through the Playwright MCP `browser_run_code` (filename: explainer/check.js)
// with a server at http://localhost:8743 from the repo root. Exercises every interactive piece at desktop and phone
// width in both themes, records console errors and horizontal overflow, and saves screenshots to artifacts/explainer/.
async (page) => {
  const base = 'http://localhost:8743/explainer/';
  const out = [];
  const errors = [];
  page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });
  page.on('pageerror', (e) => errors.push(String(e)));
  const cases = [
    { file: 'index.html', tag: 'default' },
    { file: '_test_index.html', tag: 'fixture' },
    { file: '_test_redesign.html', tag: 'redesign' },
  ];
  for (const c of cases) {
    for (const vp of [{ w: 1440, h: 900, n: 'desktop' }, { w: 390, h: 844, n: 'phone' }]) {
      for (const theme of ['light', 'dark']) {
        await page.setViewportSize({ width: vp.w, height: vp.h });
        await page.emulateMedia({ colorScheme: theme });
        await page.goto(base + c.file);
        await page.evaluate(() => { try { localStorage.clear(); } catch (e) {} });
        await page.goto(base + c.file);
        const before = await page.evaluate(() => (window.__echoCtx ? window.__echoCtx.state : 'none'));
        await page.click('#hero [data-act="clap"]');
        await page.waitForTimeout(700);
        if (c.tag === 'default') await page.screenshot({ path: `artifacts/explainer/hero-${vp.n}-${theme}.png` });
        // 1 wall: slider + drag + clap
        await page.locator('#wall [data-in="dist"]').fill('40');
        const wallReadout = await page.locator('#wall [data-out="readout"]').innerText();
        const box = await page.locator('#wall canvas').boundingBox();
        await page.mouse.move(box.x + box.width * 0.3, box.y + 60); await page.mouse.down();
        await page.mouse.move(box.x + box.width * 0.2, box.y + 60); await page.mouse.up();
        const dragged = await page.locator('#wall [data-in="dist"]').inputValue();
        await page.click('#wall [data-act="clap"]');
        // 2 row
        await page.locator('#row [data-in="spacing"]').fill('300');
        const rowReadout = await page.locator('#row [data-out="readout"]').innerText();
        await page.click('#row [data-act="clap"]');
        // 3 groove
        await page.click('#groove [data-target="motif"]');
        await page.click('#groove [data-mode="neg"]');
        const negReadout = await page.locator('#groove [data-out="readout"]').innerText();
        await page.click('#groove [data-act="target"]');
        await page.click('#groove [data-act="clap"]');
        if (c.tag === 'default') await page.locator('#groove').screenshot({ path: `artifacts/explainer/groove-neg-${vp.n}-${theme}.png` });
        await page.click('#groove [data-target="bird"]');
        await page.click('#groove [data-mode="real"]');
        const realReadout = await page.locator('#groove [data-out="readout"]').innerText();
        // 4 clap
        await page.click('#clap [data-k="0"]');
        await page.click('#clap [data-act="solo"]');
        await page.click('#clap [data-k="3"]');
        await page.click('#clap [data-act="clap"]');
        const clapReadout = await page.locator('#clap [data-out="readout"]').innerText();
        // story: rings vs scattered
        await page.locator('#rings [data-in="nudge"]').fill('10');
        const ringsReadout = await page.locator('#rings [data-out="readout"]').innerText();
        await page.click('#rings [data-act="scatter"]');
        await page.click('#rings [data-act="rings"]');
        await page.click('#rings [data-act="target"]');
        if (c.tag === 'default') await page.locator('#rings').screenshot({ path: `artifacts/explainer/story-rings-${vp.n}-${theme}.png` });
        const fine = await page.locator('details.fine summary').count();
        if (fine) await page.locator('details.fine summary').first().click();
        // 5 size
        await page.locator('#size [data-in="ms"]').fill('800');
        const sizeReadout = await page.locator('#size [data-out="readout"]').innerText();
        // results audio
        const wavButtons = await page.locator('[data-wav]').count();
        for (let i = 0; i < wavButtons; i++) { await page.locator('[data-wav]').nth(i).click(); await page.waitForTimeout(80); }
        // theme toggle
        await page.click('#themeToggle');
        const toggled = await page.evaluate(() => document.documentElement.dataset.theme);
        await page.click('#themeToggle');
        const state = await page.evaluate(() => ({
          ctx: window.__echoCtx ? window.__echoCtx.state : 'none',
          plays: window.__echoPlays,
          overflow: document.documentElement.scrollWidth - window.innerWidth,
          bg: getComputedStyle(document.body).backgroundColor,
          pending: document.querySelectorAll('.card.pending').length,
          cards: document.querySelectorAll('.card').length,
        }));
        await page.screenshot({ path: `artifacts/explainer/${c.tag}-${vp.n}-${theme}.png`, fullPage: true });
        out.push({ case: c.tag, vp: vp.n, theme, ctxBeforeGesture: before, ...state, toggled, dragged, wavButtons,
          ringsReadout, status: await page.locator('[data-out="status"]').innerText(), wallReadout, rowReadout, negReadout, realReadout, clapReadout, sizeReadout });
      }
    }
  }
  const bad = out.filter((o) => o.ctxBeforeGesture !== 'none' || o.ctx !== 'running' || o.overflow > 0 || o.toggled === undefined);
  return { errors, runs: out.length, bad, sample: out[0], statuses: [...new Set(out.map((o) => o.status))], rings: out[0].ringsReadout };
}
