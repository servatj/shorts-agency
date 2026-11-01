const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert = require('node:assert/strict');
(async () => {
  let browser;
  try { browser = await chromium.launch({executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || undefined, headless:true}); }
  catch (error) {
    if (/Executable doesn't exist/.test(error.message)) { process.exitCode=77; return; }
    throw error;
  }
  try {
    const page = await browser.newPage({viewport:{width:1440,height:1000}});
    page.setDefaultTimeout(8000);
    const errors = [];
    page.on('pageerror', e => errors.push(e.message));
    await page.route('https://**/*', route => route.abort());
    await page.goto(process.env.TEST_URL + '/social');
    await page.locator('#login-view').waitFor({state:'visible'});
    await page.locator('#username').fill('admin');
    await page.locator('#password').fill(process.env.TEST_PASSWORD);
    await page.locator('#login-submit').click();
    await page.locator('#workspace').waitFor({state:'visible'});
    assert.deepEqual(await page.locator('.rail nav button').allTextContents(), ['Inicio', 'Vídeos']);
    await page.waitForFunction(() => document.querySelectorAll('.channel-choice').length === 23);
    assert.equal(await page.locator('.profile-link').count(), 17);
    assert.match(await page.locator('.channel-option[title]').first().getAttribute('title'), /0 suscriptores.*Fecha de captura desconocida/);
    await page.locator('#social-search').fill('tiktok');
    assert.equal(await page.locator('.channel-choice').count(), 8);
    await page.locator('#social-search').fill('sample_account_00');
    assert.equal(await page.locator('.channel-choice').count(), 5);
    await page.locator('#social-search').press('Escape');
    assert.equal(await page.locator('#channel-toggle').getAttribute('aria-expanded'), 'false');
    await page.locator('#new-short').click();
    // Submission must reveal hidden invalid fields before native validity UI runs.
    const validationFailures = [];
    let invalidWrites = 0;
    const watchWrites = request => {
      if (/\/v1\/shorts(?:\/[^/]+)?$/.test(new URL(request.url()).pathname) && ['POST', 'PATCH'].includes(request.method())) invalidWrites++;
    };
    page.on('request', watchWrites);
    for (const shortcut of [false, true]) {
      for (const tab of ['publication', 'metrics']) {
        for (const title of ['', '   ']) {
          await page.locator('#editor-tab').click();
          await page.locator('#short-title').fill(title);
          await page.locator(`#${tab}-tab`).click();
          if (shortcut) await page.keyboard.press('Control+s');
          else await page.locator('#save-short').click();
          await page.waitForTimeout(100);
          if (!(await page.locator('#short-title').isVisible()) || !(await page.locator('#short-title').evaluate(e => document.activeElement === e && !e.validity.valid))) {
            validationFailures.push(`${title ? 'whitespace-only' : 'empty'} title from ${tab}, ${shortcut ? 'Ctrl+S' : 'button'}`);
          }
        }
      }
      await page.locator('#editor-tab').click();
      await page.locator('#short-title').fill('Validation QA');
      await page.locator('#summary-tab').click();
      await page.locator('#youtube_url').fill('not a URL');
      await page.locator('#editor-tab').click();
      if (shortcut) await page.keyboard.press('Control+s');
      else await page.locator('#save-short').click();
      await page.waitForTimeout(100);
      if (!(await page.locator('#youtube_url').isVisible()) || !(await page.locator('#youtube_url').evaluate(e => document.activeElement === e && !e.validity.valid))) {
        validationFailures.push(`invalid URL, ${shortcut ? 'Ctrl+S' : 'button'}`);
      }
      await page.locator('#summary-tab').click();
      await page.locator('#youtube_url').fill('');
    }
    page.off('request', watchWrites);
    assert.equal(invalidWrites, 0, 'Invalid submissions must never write records');
    await page.locator('#editor-tab').click();
    await page.locator('#short-title').fill('Guion QA <img src=x onerror=alert(1)>');
    const full = 'Inicio completo\nSegunda línea ciencia ÚNICA\n' + 'Texto legible. '.repeat(6600);
    await page.locator('#script').fill(full);
    await page.locator('#summary-tab').click();
    await page.locator('#social_account_id').selectOption('youtube:sample_account_00');
    await page.locator('#language').selectOption('en');
    assert.equal(await page.locator('#status').isDisabled(), true);
    await page.locator('#notes').fill('Notas persistentes');
    await page.locator('#save-short').click();
    await page.waitForFunction(() => document.querySelector('#save-state').textContent === 'Guardado');
    assert.deepEqual(validationFailures, [], 'Hidden invalid fields must be revealed and focused');
    const saved = await page.evaluate(async () => (await (await fetch('/v1/scripts')).json()).items);
    assert.equal(saved.length, 1);
    assert.equal(saved[0].status, 'draft');
    assert.equal(saved[0].script, full);
    assert.equal(saved[0].social_account_id, 'youtube:sample_account_00');
    assert.equal(saved[0].language, 'en');
    await page.locator('#editor-tab').click();
    await page.locator('#script-read-tab').click();
    assert.equal(await page.locator('#script-reading').textContent(), full);
    assert.equal(await page.locator('#short-list img').count(), 0);
    await page.locator('#edit-script').click();
    await page.locator('#script').fill(full + '\nEDITADO');
    await page.locator('#summary-tab').click();
    await page.locator('#status').selectOption('review');
    await page.keyboard.press('Control+s');
    await page.waitForFunction(() => document.querySelector('#save-state').textContent === 'Guardado');
    await page.reload();
    await page.locator('#short-list .short-item').first().click();
    await page.waitForFunction(() => document.querySelector('#script').value.endsWith('EDITADO'));
    assert.equal(await page.locator('#script').inputValue(), full + '\nEDITADO');
    assert.equal(await page.locator('#status').inputValue(), 'review');
    assert.equal(await page.locator('#social_account_id').inputValue(), 'youtube:sample_account_00');
    await page.locator('#new-short').click();
    await page.locator('#short-title').fill('Sin guion todavía');
    await page.locator('#save-short').click();
    await page.waitForFunction(() => document.querySelector('#total-count').textContent === '2');
    await page.locator('#back-videos').click();
    assert.match(await page.locator('#short-list').innerText(), /Sin guion/);
    await page.locator('#search').fill('única');
    assert.equal(await page.locator('#short-list .short-item').count(), 1);
    await page.locator('#search').fill('noexiste');
    assert.equal(await page.locator('#short-list .short-item').count(), 0);
    await page.locator('#search').fill('');
    assert.equal(await page.locator('#short-list .short-item').count(), 2);
    await page.locator('#library-references').click();
    await page.locator('#reference-workspace').waitFor({state:'visible'});
    await page.locator('#library-owned').click();
    await page.locator('#owned-library').waitFor({state:'visible'});
    await require('./redesign_browser.cjs')(page, full + '\nEDITADO');
    await page.setViewportSize({width:390,height:844});
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    await page.locator('#channel-toggle').click();
    await page.locator('#social-search').fill('');
    await page.locator('.channel-choice[data-channel="youtube:sample_account_00"]').click();
    await page.locator('#channel-toggle').click();
    await page.locator('#social-search').fill('sample_account_00');
    await page.locator('#channel-toggle').click();
    await page.locator('#logout').click();
    assert.equal(await page.evaluate(async () => (await fetch('/v1/social-accounts')).status), 401);
    // Sign in without reloading: a fresh document would hide stale selector state.
    await page.locator('#login-view').waitFor({state:'visible'});
    await page.locator('#username').fill('admin');
    await page.locator('#password').fill(process.env.TEST_PASSWORD);
    await page.locator('#login-submit').click();
    await page.waitForFunction(() => document.querySelector('#total-count').textContent === '2');
    await page.locator('#workspace').waitFor({state:'visible'});
    assert.deepEqual({label: await page.locator('#channel-toggle').textContent(), search: await page.locator('#social-search').inputValue()}, {label: 'Todos los canales ⌄', search: ''});
    await page.locator('#library-owned').click();
    assert.equal(await page.locator('#short-list .short-item').count(), 2);
    await page.locator('#channel-toggle').click();
    assert.equal(await page.locator('.channel-choice').count(), 23);
    await page.locator('#social-search').press('Escape');
    assert.equal(await page.locator('#library-owned').getAttribute('aria-current'), 'page');
    assert.deepEqual(errors, []);
    console.log('Browser PASS: 21 socials/17 safe links, filters, hidden-tab validation via button/Ctrl+S, fresh login and channel reset, full script create/read/edit/reload, draft-only creation, social association, empty scripts, navigation, mobile, logout, no JS errors.');
  } finally { await browser.close(); }
})().catch(e => { console.error(e); process.exitCode=1; });
