const assert = require('node:assert/strict');
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
(async () => {
  const browser = await chromium.launch({headless:true, executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || undefined});
  try {
    const page = await browser.newPage({viewport:{width:1536,height:1024}});
    const errors = []; page.on('pageerror', e => errors.push(e.message));
    let brokenRequests = 0;
    await page.route('https://**/*', route => {
      if (route.request().url() === 'https://images.example/cover.svg') return route.fulfill({contentType:'image/svg+xml', body:'<svg xmlns="http://www.w3.org/2000/svg" width="90" height="160"><rect width="90" height="160" fill="teal"/></svg>'});
      if (route.request().url().includes('broken.jpg')) brokenRequests++;
      return route.abort();
    });
    await page.goto(process.env.TEST_URL);
    await page.locator('#username').fill('admin'); await page.locator('#password').fill(process.env.TEST_PASSWORD);
    await page.locator('#login-submit').click(); await page.locator('#workspace').waitFor({state:'visible'});
    const create = async fields => page.evaluate(async fields => {
      const me = await (await fetch('/auth/me')).json();
      const response = await fetch('/v1/shorts', {method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':me.csrf_token},body:JSON.stringify({title:'Synthetic preview',...fields})});
      if (response.status !== 201) throw new Error(await response.text());
      return response.json();
    }, fields);
    await create({status:'published', thumbnail_url:'https://images.example/cover.svg', preview_url:'https://www.tiktok.com/@sample_account/video/1234567890123456789'});
    await page.locator('#refresh-list').click();
    await page.locator('#short-list img').waitFor();
    assert.equal(await page.locator('#short-list img').getAttribute('loading'), 'lazy');
    assert.equal(await page.locator('#short-list img').getAttribute('referrerpolicy'), 'no-referrer');
    assert.match(await page.locator('#short-list img').getAttribute('alt'), /Synthetic preview/);
    await page.locator('#short-list .short-item').first().hover();
    assert.equal(await page.locator('#inspector img').count(), 1);
    await page.locator('#short-list .short-item').first().click();
    await page.locator('#detail').waitFor({state:'visible'});
    assert.equal(await page.locator('#preview-content img').count(), 1);
    assert.equal(await page.locator('#preview-content img').evaluate(e => getComputedStyle(e).objectFit), 'contain');
    assert.match(await page.locator('#script-reading').innerText(), /Guion no disponible/);
    assert.equal(await page.locator('iframe').count(), 0);
    await page.locator('#summary-tab').click();
    for (const format of ['16:9', '9:16']) {
      await page.locator('#format').selectOption(format);
      const geometry = await page.locator('#preview-content img').evaluate(img => {
        const box = img.getBoundingClientRect(), stage = document.querySelector('#preview-stage').getBoundingClientRect();
        const button = document.querySelector('#preview-content button').getBoundingClientRect();
        return {height:box.height, fits:box.top >= stage.top && box.bottom <= stage.bottom, buttonFits:button.bottom <= stage.bottom};
      });
      assert.ok(geometry.height > 10 && geometry.fits && geometry.buttonFits, JSON.stringify({format,...geometry}));
    }
    await page.locator('#thumbnail_url').fill('https://images.example/broken.jpg');
    await page.locator('#save-short').click();
    await page.waitForFunction(() => document.querySelector('#save-state').textContent === 'Guardado');
    await page.waitForFunction(() => !document.querySelector('#preview-content img'));
    assert.match(await page.locator('#preview-content').innerText(), /Imagen no disponible/);
    const attempts = brokenRequests;
    await page.waitForTimeout(250); assert.equal(brokenRequests, attempts);
    const source = page.locator('#preview-source-links a');
    assert.equal(await source.isVisible(), true);
    await page.getByRole('button', {name:'Cargar vista previa', exact:true}).click();
    const frame = page.locator('#preview-content iframe');
    assert.equal(await frame.getAttribute('src'), 'https://www.tiktok.com/player/v1/1234567890123456789?autoplay=0&loop=0');
    assert.equal(await frame.getAttribute('referrerpolicy'), 'strict-origin-when-cross-origin');
    assert.match(await frame.getAttribute('title'), /TikTok/);
    assert.notEqual(await frame.getAttribute('allowfullscreen'), null);
    assert.equal(await source.isVisible(), true);
    assert.match(await page.locator('#preview-help').innerText(), /original/);
    await page.getByRole('button', {name:'Volver a la portada', exact:true}).click({timeout:2000});
    assert.equal(await frame.count(), 0);
    assert.match(await page.locator('#preview-content').innerText(), /Imagen no disponible/);
    assert.equal(await source.isVisible(), true);
    assert.equal(await page.getByRole('button', {name:'Cargar vista previa', exact:true}).count(), 1);
    assert.equal(await page.getByRole('button', {name:'Volver a la portada', exact:true}).count(), 0);
    assert.doesNotMatch(await page.locator('#preview-help').innerText(), /cargado|reproduciendo/i);
    const csp = (await page.request.get(process.env.TEST_URL + '/')).headers()['content-security-policy'];
    assert.match(csp, /frame-src https:\/\/www.youtube-nocookie.com https:\/\/www.tiktok.com;/);
    const changePreview = async url => {
      await page.locator('#preview_url').fill(url);
      await page.locator('#preview_url').blur();
      assert.equal(await page.locator('iframe').count(), 0);
    };
    for (const url of ['https://tiktok.com.evil.example/@x/video/123', 'https://evil.tiktok.com/@x/video/123', 'https://user@www.tiktok.com/@x/video/123', 'https://www.tiktok.com/@x/video/%31', 'https://www.tiktok.com/@x/video/123/extra', 'https://www.tiktok.com/@x/../@x/video/123', 'https://www.tiktok.com/@x/video/123#x', 'http://www.tiktok.com/@x/video/123', 'https://www.tiktok.com:444/@x/video/123']) {
      await changePreview(url);
      assert.equal(await page.getByRole('button', {name:'Cargar vista previa', exact:true}).count(), 0, url);
    }
    await changePreview('https://www.instagram.com/reel/SYNTHETIC/');
    assert.equal(await page.getByRole('button', {name:'Cargar vista previa', exact:true}).count(), 0);
    assert.equal(await source.getAttribute('href'), 'https://www.instagram.com/reel/SYNTHETIC/');
    await changePreview('https://tiktok.com/@sample/video/123');
    await page.locator('#youtube_url').fill('https://youtu.be/SAMPLE00001');
    await page.locator('#youtube_url').blur();
    await page.getByRole('button', {name:'Cargar vista previa', exact:true}).click();
    assert.match(await frame.getAttribute('src'), /youtube-nocookie.com\/embed\/SAMPLE00001/);
    assert.equal(await page.locator('#youtube-open').isVisible(), true);
    assert.equal(await source.isVisible(), true);
    await changePreview('/media/synthetic.webm');
    await page.getByRole('button', {name:'Cargar vista previa', exact:true}).click();
    assert.equal(await page.locator('#preview-content video').count(), 1);
    assert.equal(await page.locator('iframe').count(), 0);
    assert.equal(await page.locator('video').getAttribute('autoplay'), null);
    assert.equal(await page.locator('script[src*="tiktok"]').count(), 0);
    assert.deepEqual(errors, []);
    console.log('Preview browser acceptance passed: thumbnails, failure fallback, explicit embeds, strict URLs, source links, metadata save, media priority.');
  } finally { await browser.close(); }
})().catch(e => { console.error(e); process.exit(1); });
