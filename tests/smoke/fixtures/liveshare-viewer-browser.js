async (page, params) => {
  const target = params.base + '/?shareId=' + params.share;
  const rpc = params.base + '/__share/rpc?shareId=' + params.share;
  const auth = { Authorization: 'Bearer fixture-viewer' };
  const uploads = [];
  const failedAssets = [];
  const pageErrors = [];
  let prompt;
  page.on('pageerror', error => pageErrors.push(String(error)));
  await page.route('**/*', async route => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.origin !== params.base) return route.abort();
    if (url.href === rpc && request.method() === 'POST') {
      const body = request.postDataJSON();
      if (body.path === '/api/fileUploads/upload') {
        const args = body.body.payload.args;
        const started = Date.now();
        const response = await route.fetch({ headers: { ...request.headers(), ...auth } });
        const answer = await response.json();
        uploads.push({ agentId: args.agentId, name: args.request.name, mediaType: args.request.mediaType ?? null,
          elapsedMs: Date.now() - started, status: response.status(), ok: answer.result?.ok === true, error: answer.result?.error ?? answer.error });
        return route.fulfill({ response });
      }
      if (body.path === '/api/session/prompt') prompt = body.body.payload.args.request;
      return route.continue({ headers: { ...request.headers(), ...auth } });
    }
    if (request.method() === 'GET' && url.pathname === '/__liveshare/context'
        && url.searchParams.get('shareId') === params.share) {
      return route.fulfill({ json: { shareId: params.share, sessionId: params.session, ownerDisplayName: 'Fixture Owner',
        viewer: { subjectId: 'reader', displayName: 'Fixture Viewer' },
        capabilities: { sessionMode: 'view', readOnly: true, online: true, allowsFork: false } } });
    }
    if (request.method() === 'GET' && url.pathname === '/health') {
      return route.fulfill({ json: { release_id: 'mobile-harness-test-relay' } });
    }
    if (url.href === target) {
      return route.fulfill({ status: 200, contentType: 'text/html; charset=utf-8', body: params.html });
    }
    if (request.method() !== 'GET') return route.fulfill({ status: 404 });
    const path = url.pathname.slice(1) + url.search;
    const reply = await page.request.post(rpc, { headers: auth, data: { op: 'asset', path } });
    if (!reply.ok()) { failedAssets.push([url.pathname,reply.status()]); return route.fulfill({ status: reply.status() }); }
    const asset = await reply.json();
    return route.fulfill({ status: 200, contentType: asset.contentType, body: Buffer.from(asset.base64, 'base64') });
  });
  await page.goto(target, { waitUntil: 'domcontentloaded' });
  try {
    const input = page.locator('input[type=file]:enabled').first();
    await input.waitFor({ state: 'attached', timeout: 30000 });
    await input.setInputFiles(params.files.map(file => ({ name:file.name, mimeType:file.type, buffer:Buffer.from(file.data,'base64') })));
    const editor = page.locator('[contenteditable=true]').first();
    await editor.fill(params.prompt);
    const limit = Date.now()+40000;
    while (uploads.length < 3 && Date.now() < limit) await new Promise(resolve => setTimeout(resolve, 200));
    if (uploads.length !== 3) throw new Error('Actual composer did not submit all three uploads: '+JSON.stringify(uploads));
    if (uploads.some(item => String(item.agentId) !== params.session || !item.ok || item.elapsedMs >= 20000)) {
      throw new Error('Actual upload did not produce authorized receipts: '+JSON.stringify(uploads));
    }
    for (let attempt=0; !prompt && attempt<8; attempt++) {
      await editor.press('Enter');
      await new Promise(resolve => setTimeout(resolve, 500));
    }
    if (prompt && prompt.content.filter(part => part.type==='file').length !== 3) throw new Error('Missing staged receipts');
    if (!prompt) throw new Error('The viewer composer did not submit the staged attachments');
    return 'MH_RESULT:'+JSON.stringify({requestId:prompt.requestId, uploads});
  } catch (error) {
    return 'MH_DEBUG:'+JSON.stringify({error:String(error), failedAssets, pageErrors,
      body:(await page.locator('body').innerText()).slice(0,1500)});
  }
}
