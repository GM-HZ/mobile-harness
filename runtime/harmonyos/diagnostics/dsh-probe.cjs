const fs = require('node:fs');
const http = require('node:http');
const cli = '/dsh/node_modules/@deepseek-ai/dsh/lib/bin.js';
function httpGet(url, headers = {}) {
  return new Promise((resolve, reject) => {
    const req = http.get(url, { headers }, (res) => {
      let body = '';
      res.on('data', chunk => { body = (body + chunk).slice(0, 1048576); });
      res.on('end', () => resolve({ status: res.statusCode, body, headers: res.headers }));
    });
    req.on('error', reject);
    req.setTimeout(1000, () => req.destroy(Error('http timeout')));
  });
}
function makeResponse(reqBody, state) {
  const input = JSON.parse(reqBody);
  const tools = (input.tools || []).map(t => t.name);
  const toolResult = (input.messages || []).some(message => Array.isArray(message.content) &&
    message.content.some(block => block.type === 'tool_result' && !block.is_error &&
      JSON.stringify(block.content).includes('DSH_BASH_OK')));
  if (toolResult) state.sawToolResult = true;
  const tool = !toolResult && !state.issuedTool && tools.find(name => /^bash$/i.test(name));
  if (tool) state.issuedTool = true;
  const stop = tool ? 'tool_use' : 'end_turn';
  const block = tool
    ? { type: 'tool_use', id: 'toolu_harmony_probe', name: tool, input: {} }
    : { type: 'text', text: '' };
  const delta = tool
    ? { type: 'input_json_delta', partial_json: JSON.stringify({ command: "printf 'DSH_BASH_OK\\n'", description: 'Local probe' }) }
    : { type: 'text_delta', text: 'DSH_FIXTURE_OK' };
  return [
    { type: 'message_start', message: { id: 'msg_harmony_probe', type: 'message', role: 'assistant', model: input.model, content: [], stop_reason: null, stop_sequence: null, usage: { input_tokens: 5, output_tokens: 0 } } },
    { type: 'content_block_start', index: 0, content_block: block },
    { type: 'content_block_delta', index: 0, delta },
    { type: 'content_block_stop', index: 0 },
    { type: 'message_delta', delta: { stop_reason: stop, stop_sequence: null }, usage: { output_tokens: 5 } },
    { type: 'message_stop' }
  ].map(event => 'event: ' + event.type + '\ndata: ' + JSON.stringify(event) + '\n\n').join('');
}
async function main() {
  const fixedCommand = process.argv.includes('headless-command');
  const patched = fixedCommand || process.argv.includes('headless-patch');
  const headless = patched || process.argv.includes('headless');
  const state = { requests: 0, issuedTool: false, sawToolResult: false };
  process.env.HOME = '/root';
  process.env.DSH_HOME = '/tmp/dsh-poc-home';
  process.env.NO_COLOR = '1';
  process.env.NARB_DISABLE_NATIVE_CACHE = '1';
  process.env.SHELL = '/bin/bash';
  process.chdir('/tmp');
  console.log('DSH_BOOT', JSON.stringify({mode: headless ? 'headless' : 'web', version: require('/dsh/node_modules/@deepseek-ai/dsh/package.json').version, cwd:process.cwd()}));
  if (patched) {
    const assert = require('node:assert/strict');
    const native = require('/harmony-publish.node');
    const first = '/tmp/harmony-publish-source', second = '/tmp/harmony-publish-target';
    fs.writeFileSync(first,'new');
    fs.writeFileSync(second,'old');
    assert.equal(native.renameNoReplace(first,second),17);
    assert.equal(fs.readFileSync(second,'utf8'),'old');
    assert.equal(fs.readFileSync(first,'utf8'),'new');
    fs.unlinkSync(second);
    assert.equal(native.renameNoReplace(first,second),0);
    assert.equal(fs.readFileSync(second,'utf8'),'new');
    assert.equal(fs.existsSync(first),false);
    fs.unlinkSync(second);
    console.log('EXCLUSIVE_RENAME_OK');

    globalThis.__harmonyPocPublishNoReplace = (source, target) => {
      const code = native.renameNoReplace(source,target);
      if (code) throw Object.assign(new Error('exclusive rename errno=' + code),
        { code: code === 17 ? 'EEXIST' : 'EIO', errno: -code });
      console.log('DSH_PUBLISH_RENAME_OK');
    };
    require('node:module').registerHooks({
      load(url, context, nextLoad) {
        const loaded = nextLoad(url, context);
        if (url !== 'file:///dsh/node_modules/@deepseek-ai/dsh-session-persistence-jsonl/lib/index.js') return loaded;
        const text = typeof loaded.source === 'string' ? loaded.source : Buffer.from(loaded.source).toString('utf8');
        const original = 'await link(tmp, finalPath);';
        if (text.split(original).length !== 2) throw Error('unexpected pinned DSH materialization implementation');
        const source = text.replace(original, "try { await link(tmp, finalPath); } catch (error) { if (error?.code !== 'EACCES') throw error; globalThis.__harmonyPocPublishNoReplace(tmp, finalPath); }");
        return { ...loaded, source };
      }
    });
  }
  if (headless) {
    const fixture = http.createServer(async (req, res) => {
      try {
        if (req.method !== 'POST' || !req.url.includes('/messages')) { res.writeHead(404).end(); return; }
        let body = '';
        for await (const chunk of req) body += chunk;
        state.requests++;
        res.writeHead(200, { 'content-type': 'text/event-stream' }).end(makeResponse(body, state));
      } catch { res.writeHead(500).end(); }
    });
    await new Promise((resolve, reject) => {
      fixture.once('error', reject);
      fixture.listen(0, '127.0.0.1', resolve);
    });
    fixture.unref();
    process.env.DEEPSEEK_BASE_URL = 'http://127.0.0.1:' + fixture.address().port;
    process.env.DEEPSEEK_API_KEY = 'local-validation-fixture';
    const sessionRoot = '/tmp/dsh-poc-home/sessions/--tmp--';
    const sessions = () => fs.existsSync(sessionRoot) ? fs.readdirSync(sessionRoot) : [];
    const existing = new Set(sessions());
    process.on('exit', code => {
      const added = sessions().filter(name => !existing.has(name));
      const persisted = added.map(name => {
        const file = sessionRoot + '/' + name + '/session.v4.jsonl.zstd';
        return fs.existsSync(file) ? fs.statSync(file).size : 0;
      });
      console.log('DSH_HEADLESS', JSON.stringify({ ...state, fixedCommand, persisted, code }));
    });
    const permissions = fixedCommand ? ['--permission-mode', 'danger-full-access'] : [];
    process.argv = ['/bin/node', cli, '--profile','headless','--json',...permissions,'Run the bash tool once to print DSH_BASH_OK, then finish.'];
  } else {
    process.argv = ['/bin/node', cli, '--profile','web','--host','127.0.0.1','--port','19592','--no-open'];
    let checking = false;
    let launchUrl;
    const base = 'http://127.0.0.1:19592/';
    const print = console.log.bind(console);
    console.log = (...args) => {
      const match = typeof args[0] === 'string' && /^dsh web: (http:\/\/127\.0\.0\.1:19592\/\?token=[^\s]+)$/.exec(args[0]);
      if (match) {
        launchUrl = match[1];
        print('DSH_WEB_URL_READY');
      } else {
        print(...args);
      }
    };
    const poll = setInterval(async () => {
      if (checking || !launchUrl) return;
      checking = true;
      try {
        const unauthenticated = await httpGet(base);
        const exchange = await httpGet(launchUrl);
        const cookie = (exchange.headers['set-cookie'] || []).map(value => value.split(';')[0]).join('; ');
        if (!cookie) throw Error('launch token did not create a cookie');
        const response = await httpGet(base, { Cookie: cookie });
        const html = /<html/i.test(response.body);
        const dist = '/dsh/node_modules/@deepseek-ai/dsh-web-frontend/dist';
        const template = fs.readFileSync(dist + '/index.html','utf8');
        const scripts = [...template.matchAll(/<script[^>]+src="([^"]+)"/g)].map(match => match[1]);
        const entry = scripts.find(src => /(?:^|\/)assets\/index-/.test(src));
        const assetUrl = entry ? new URL(entry, base) : null;
        const asset = assetUrl ? await httpGet(assetUrl, { Cookie: cookie }) : null;
        const localAsset = assetUrl && '/dsh/node_modules/@deepseek-ai/dsh-web-frontend/dist' + assetUrl.pathname;
        const fileExists = !!localAsset && fs.existsSync(localAsset);
        print('DSH_WEB', JSON.stringify({ unauthorized: unauthenticated.status, exchange: exchange.status,
          status: response.status, html, referencesEntry: !!entry && response.body.includes(entry), scripts: scripts.map(src => new URL(src, base).pathname),
          scriptStatus: asset?.status ?? null, fileExists }));
        clearInterval(poll);
        setTimeout(() => process.exit(unauthenticated.status === 401 && response.status === 200 && html &&
          asset?.status === 200 ? 0 : 2), 50);
      } catch (error) { print('DSH_WEB_PROBE_ERROR', String(error).replace(/token=[^&\s]+/g, 'token=[redacted]')); }
      finally { checking = false; }
    }, 300);
    setTimeout(() => { console.log('DSH_WEB_TIMEOUT'); process.exit(1); }, 90000).unref();
  }
  await (await import('file://' + cli)).runCli();
}
main().catch(error => { console.error('DSH_PROBE_ERROR', require('node:util').inspect(error, {depth:6,breakLength:180})); process.exit(1); });
