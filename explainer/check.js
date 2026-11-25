// Browser check for the explainer, run through the Playwright MCP `browser_run_code` (filename: explainer/check.js)
// with a server at http://localhost:8743 from the repo root. Build first:
//   uv run python explainer/build.py
//   uv run python explainer/make_fixture.py && uv run python explainer/build.py --runs explainer/_fixture_runs --out explainer/_test_verdicts.html
// The fixture build carries every verdict state (pass, fail, not established, not scored). Exercises every interactive piece at desktop and phone
// width in both themes, records console errors and horizontal overflow, and saves screenshots to artifacts/explainer/.
async (page0) => {
  // own browser context: other agents may drive the shared tab
  const ctx = await page0.context().browser().newContext();
  const page = await ctx.newPage();
  const base = 'http://localhost:8743/explainer/';
  const out = [];
  const errors = [];
  page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });
  page.on('pageerror', (e) => errors.push(String(e)));
  const cases = [
    { file: 'index.html', tag: 'default' },
    { file: '_test_verdicts.html', tag: 'fixture' },
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
        if (c.tag === 'default') await page.screenshot({ path: `artifacts/explainer/final2-hero-${vp.n}-${theme}.png` });
        // what works: every whistle button
        const wb = await page.locator('[data-whistle]').count();
        const p0 = await page.evaluate(() => window.__echoPlays);
        for (let i = 0; i < wb; i++) { await page.locator('[data-whistle]').nth(i).click(); await page.waitForTimeout(150); }
        const whistlePlays = (await page.evaluate(() => window.__echoPlays)) - p0;
        if (c.tag === 'default') await page.locator('#whistle').screenshot({ path: `artifacts/explainer/final2-whistle-${vp.n}-${theme}.png` });
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
        if (c.tag === 'default') await page.locator('#groove').screenshot({ path: `artifacts/explainer/final2-groove-${vp.n}-${theme}.png` });
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
        if (c.tag === 'default') await page.locator('#rings').screenshot({ path: `artifacts/explainer/final2-rings-${vp.n}-${theme}.png` });
        // thicker air cartoon
        await page.locator('#thick [data-in="radius"]').fill('8');
        await page.locator('#thick [data-in="half"]').fill('5');
        await page.locator('#thick [data-in="depth"]').fill('100');
        const thickReadout = await page.locator('#thick [data-out="readout"]').innerText();
        for (const b of await page.locator('#thick [data-cal]:visible').all()) await b.click();
        const thickReal = await page.locator('#thick [data-out="real"]').innerText();
        if (c.tag === 'default') await page.locator('#thick').screenshot({ path: `artifacts/explainer/final2-thick-${vp.n}-${theme}.png` });
        const fine = await page.locator('details.fine summary').count();
        if (fine) await page.locator('details.fine summary').first().click();
        // 5 size
        await page.locator('#size [data-in="ms"]').fill('800');
        const sizeReadout = await page.locator('#size [data-out="readout"]').innerText();
        // results audio
        const wavButtons = await page.locator('[data-wav]').count();
        const p1 = await page.evaluate(() => window.__echoPlays);
        for (let i = 0; i < wavButtons; i++) { await page.locator('[data-wav]').nth(i).click(); await page.waitForTimeout(120); }
        await page.waitForTimeout(300);
        const wavPlays = (await page.evaluate(() => window.__echoPlays)) - p1;
        const states = await page.evaluate(() => [...new Set([...document.querySelectorAll('[data-v]')].map((el) => el.dataset.v))].sort());
        if (vp.n === 'desktop' || c.tag === 'default') {
          await page.locator('#results').screenshot({ path: `artifacts/explainer/final2-results-${c.tag}-${vp.n}-${theme}.png` });
          if (c.tag === 'default') {
            await page.locator('#works').scrollIntoViewIfNeeded();
            await page.screenshot({ path: `artifacts/explainer/final2-works-${vp.n}-${theme}.png` });
            await page.locator('#try').scrollIntoViewIfNeeded();
            await page.screenshot({ path: `artifacts/explainer/final2-try-${vp.n}-${theme}.png` });
          }
        }
        // theme toggle
        await page.click('#themeToggle');
        const toggled = await page.evaluate(() => document.documentElement.dataset.theme);
        await page.click('#themeToggle');
        const state = await page.evaluate(() => ({
          ctx: window.__echoCtx ? window.__echoCtx.state : 'none',
          plays: window.__echoPlays,
          overflow: Math.max(document.documentElement.scrollWidth - window.innerWidth,
            ...[...document.querySelectorAll('body *')].map((el) => { const r = el.getBoundingClientRect(); return r.width ? Math.round(r.right - window.innerWidth) : -1; })),
          bg: getComputedStyle(document.body).backgroundColor,
          pending: document.querySelectorAll('.card.pending').length,
          cards: document.querySelectorAll('.card').length,
        }));
        if (vp.n === 'desktop' && theme === 'light') await page.screenshot({ path: `artifacts/explainer/final2-${c.tag}-${vp.n}-${theme}.png`, fullPage: true });
        out.push({ case: c.tag, vp: vp.n, theme, ctxBeforeGesture: before, ...state, toggled, dragged, wavButtons, wavPlays, wb, whistlePlays, states,
          ringsReadout, thickReadout, thickReal, status: await page.locator('[data-out="status"]').innerText(), wallReadout, rowReadout, negReadout, realReadout, clapReadout, sizeReadout });
      }
    }
  }
  await ctx.close();
  const need = { fixture: ['ear:none', 'ear:pass', 'revised:fail', 'revised:none', 'revised:null', 'revised:pass', 'strict:fail', 'strict:pass'] };
  const bad = out.filter((o) => o.ctxBeforeGesture !== 'none' || o.ctx !== 'running' || o.overflow > 0 || o.toggled === undefined
    || o.wavPlays < o.wavButtons || o.whistlePlays < o.wb || (need[o.case] || []).some((s) => !o.states.includes(s)));
  return { errors, runs: out.length, bad: bad.map((o) => ({ case: o.case, vp: o.vp, theme: o.theme, ctx: o.ctx, overflow: o.overflow, wavPlays: o.wavPlays, wavButtons: o.wavButtons, whistlePlays: o.whistlePlays, wb: o.wb, states: o.states })),
    statuses: [...new Set(out.map((o) => o.status))], states: [...new Set(out.map((o) => `${o.case}: ${o.states.join(' ')}`))],
    rings: out[0].ringsReadout, thick: out[0].thickReadout, thickReal: out[0].thickReal, wavs: out.map((o) => `${o.wavPlays}/${o.wavButtons}, whistle ${o.whistlePlays}/${o.wb}`).join('; ') };
}
