'use strict';

const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { stripTypeScriptTypes } = require('node:module');
const path = require('node:path');

async function main() {
  const origin = 'http://127.0.0.1:19592/';
  const cookie = 'dsh-auth-fixture=v1.synthetic.signature';
  const apiKey = 'test-only-' + 'a'.repeat(32);
  const credential = 'MOBILE_HARNESS_LOCAL_INFERENCE_KEY';
  const portal = { provider: 'deepseek-cloud', model: 'test-cloud', reasoningEffort: 'high' };
  const base = { provider: 'factory-default', model: 'factory-model' };
  const providers = { cloud: { api: 'openai-responses' } };
  let selected = { ...portal };
  let revision = 1;
  let conflictOnce = true;
  let calls = 0;
  let destroyed = 0;
  let corruptEnvelope = false;
  const credentials = new Map();

  function settings(method, args) {
    if (method === 'settings/describe') {
      assert.deepEqual(args, {});
      return {
        ok: true,
        value: {
          writable: true,
          namespaces: [
            { ns: 'llm-pi-ai', revision, value: { providers } },
            { ns: 'agent-default-model', revision, value: selected, base },
          ],
        },
      };
    }
    if (method === 'credentials/set' || method === 'credentials/unset') {
      assert.equal(args.ref, credential);
      if (method.endsWith('/set')) credentials.set(args.ref, args.value);
      else credentials.delete(args.ref);
      return { ok: true };
    }
    assert.equal(args.expectedRevision, revision);
    if (method === 'settings/replace') {
      assert.equal(args.ns, 'agent-default-model');
      selected = args.section;
    } else {
      assert.equal(method, 'settings/mutate');
      assert.equal(args.ns, 'llm-pi-ai');
      assert.equal(args.ops.length, 1);
      const [operation] = args.ops;
      assert.deepEqual(operation.path, ['providers', 'mobile-harness-local']);
      if (conflictOnce) {
        conflictOnce = false;
        providers.concurrent = { api: 'anthropic-messages' };
        revision++;
        return { ok: false, error: { code: 'settings/conflict', message: 'discard fixture payload' } };
      }
      if (operation.op === 'set') providers[operation.path[1]] = operation.value;
      else {
        assert.equal(operation.op, 'unset');
        delete providers[operation.path[1]];
      }
    }
    revision++;
    return { ok: true };
  }

  let interceptor;
  globalThis.localModelRouteSdk = {
    InterceptorType: { REDIRECTION: 'redirect' },
    RequestMethod: { POST: 'POST' },
    HttpDataType: { STRING: 'string' },
    HttpInterceptorChain: class {
      addChain(chain) { [interceptor] = chain; return true; }
      apply() { return true; }
    },
    createHttp() {
      return {
        async request(address, options) {
          calls++;
          const envelope = JSON.parse(options.extraData);
          assert.equal(address, origin + 'api/' + envelope.method);
          assert.equal(envelope.type, 'client-request');
          assert.equal(options.method, 'POST');
          assert.deepEqual(options.header, { 'Content-Type': 'application/json', Cookie: cookie });
          assert.equal(options.usingProxy, false);
          assert.equal(options.usingCache, false);
          assert.equal(interceptor.interceptorType, 'redirect');
          assert.equal(await interceptor.interceptorHandle({}, {}), false);
          const result = settings(envelope.method, envelope.payload.args);
          return {
            responseCode: 200,
            result: JSON.stringify({
              type: 'server-response',
              rpcId: corruptEnvelope ? 'wrong-id' : envelope.rpcId,
              result,
            }),
          };
        },
        destroy() { destroyed++; },
      };
    },
  };

  const file = path.join(__dirname, '../../apps/harmonyos/entry/src/main/ets/runtime/LocalModelRoute.ets');
  const source = readFileSync(file, 'utf8').replace(/^import .*;\n/gm, '');
  const code = stripTypeScriptTypes('const http = globalThis.localModelRouteSdk;\n' + source);
  const { LocalModelRoute, LOCAL_MODEL_PROVIDER } = await import('data:text/javascript;base64,' + Buffer.from(code).toString('base64'));
  const storeFile = path.join(path.dirname(file), 'LocalModelStore.ets');
  const catalogCode = stripTypeScriptTypes(readFileSync(storeFile, 'utf8').replace(/^import .*;\n/gm, ''));
  const { LOCAL_MODELS } = await import('data:text/javascript;base64,' + Buffer.from(catalogCode).toString('base64'));
  const nativeFile = path.join(__dirname, '../../runtime/harmonyos/native/dsh-local-inference.cpp');
  const nativeCode = readFileSync(nativeFile, 'utf8');
  const nativeContext = Number(nativeCode.match(/params\.n_ctx = (\d+);/)?.[1]);
  const nativeOutput = Number(nativeCode.match(/params\.n_predict = (\d+);/)?.[1]);
  const firstPromptTokens = 9548;
  assert(nativeContext >= firstPromptTokens + nativeOutput, 'native budget must fit the observed DSH first turn');
  for (const model of LOCAL_MODELS) {
    assert.equal(model.contextWindow, nativeContext, model.id);
    assert.equal(model.maxTokens, nativeOutput, model.id);
  }

  const session = { url: origin, cookie: cookie + '; HttpOnly; Path=/' };
  assert.throws(() => new LocalModelRoute({ ...session, url: 'https://example.test/' }));
  assert.throws(() => new LocalModelRoute({ ...session, safe: true }));
  assert.throws(() => new LocalModelRoute({ ...session, cookie: 'invalid' }));
  const route = new LocalModelRoute(session);
  assert.deepEqual(await route.readDefault(), portal);

  const [lfm, qwen] = LOCAL_MODELS.map(model => ({
    id: model.id, name: model.label, contextWindow: model.contextWindow, maxTokens: model.maxTokens,
  }));
  await assert.rejects(route.prefer(lfm), /启动所选本地模型/);
  await route.register(lfm, apiKey);
  const added = providers[LOCAL_MODEL_PROVIDER];
  assert.equal(added.baseURL, 'http://127.0.0.1:39765/v1');
  assert.equal(added.apiKeyEnv, credential);
  assert.equal(added.models[0].id, lfm.id);
  assert.equal(added.models[0].contextWindow, nativeContext);
  assert.equal(added.streamIdleTimeoutMs, 480000);
  assert.equal(added.retryPolicy.maxRetries, 0);
  assert(!JSON.stringify(added).includes(apiKey));
  assert.equal(credentials.get(credential), apiKey);
  assert.deepEqual(await route.prefer(lfm), portal);
  assert.deepEqual(selected, { provider: LOCAL_MODEL_PROVIDER, model: lfm.id });
  await assert.rejects(route.unregister(), /恢复非本地默认/);
  await route.register(qwen, apiKey);
  assert.equal(await route.prefer(qwen), undefined);
  assert.deepEqual(selected, { provider: LOCAL_MODEL_PROVIDER, model: qwen.id });
  await route.restore(portal);
  assert.deepEqual(selected, portal);
  selected = { provider: 'another-provider', model: 'manually-chosen' };
  await route.restore(portal);
  assert.deepEqual(selected, { provider: 'another-provider', model: 'manually-chosen' });
  await route.prefer(qwen);
  await route.restore(undefined);
  assert.deepEqual(selected, base);

  await route.unregister();
  assert(!credentials.has(credential));
  assert.deepEqual(providers, { cloud: { api: 'openai-responses' }, concurrent: { api: 'anthropic-messages' } });
  providers[LOCAL_MODEL_PROVIDER] = { ...added, baseURL: 'https://example.test/v1' };
  await assert.rejects(route.register(qwen, apiKey), /名称已被其他配置/);
  assert(!credentials.has(credential));
  corruptEnvelope = true;
  await assert.rejects(route.readDefault(), /响应无效/);
  assert.equal(destroyed, calls);
  console.log('LOCAL_INFERENCE_ROUTE_CONTRACT_OK');
}

main().catch(error => {
  console.error(error.message);
  process.exitCode = 1;
});
