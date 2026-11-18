'use strict';
const { EventEmitter } = require('node:events');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const { isMainThread, parentPort, Worker, workerData } = require('node:worker_threads');

function createSharedPtcPolicy(mark) {
  const turns = new WeakMap();
  const grants = new WeakMap();
  const nativeRuntimes = new WeakSet();
  const within = (root, candidate) => {
    const relative = path.relative(root, candidate);
    return relative !== '..' && !relative.startsWith('../') && !path.isAbsolute(relative);
  };
  const physicalDirectory = value => {
    if (typeof value !== 'string' || !path.isAbsolute(value) || path.normalize(value) !== value || value === '/') {
      throw new Error('Shared PTC requires a specific physical workspace');
    }
    return value;
  };
  function permissions(session) {
    const checks = turns.get(session)?.checks ?? [];
    return {
      admitted: checks.length > 0 && checks.every(check => check('read')),
      writable: checks.length > 0 && checks.every(check => check('write')),
    };
  }
  return {
    observeTurn(session, turn, check) {
      let state = turns.get(session);
      if (state?.turn !== turn) {
        state = { turn, checks: [] };
        turns.set(session, state);
      }
      if (check) {
        const admittedToWrite = check('write');
        state.checks.push(permission => (permission === 'read' || admittedToWrite) && check(permission));
      }
    },
    canSourceWrite(session) {
      const { admitted, writable } = permissions(session);
      return admitted && writable;
    },
    capture(token, grant) {
      if (typeof token !== 'symbol') throw new Error('Shared PTC requires a runtime execution token');
      grants.set(token, grant);
    },
    trustRuntime(runtime) {
      nativeRuntimes.add(runtime);
    },
    take(token) {
      const grant = grants.get(token);
      if (grant) grants.delete(token);
      return grant;
    },
    async restrict(runtime, standing, sourceGrant, args, signal) {
      if (!nativeRuntimes.has(runtime)) {
        throw new Error('Shared PTC requires the HarmonyOS file supervisor');
      }
      if (!standing || !['read-only', 'workspace-write', 'danger-full-access'].includes(standing.mode)) {
        throw new Error('Shared PTC requires a standing file policy');
      }
      if (args.sandbox_permissions !== undefined || args.justification !== undefined) {
        throw new Error('A shared program cannot request wider sandbox permissions');
      }
      signal.throwIfAborted();
      const grant = await sourceGrant();
      signal.throwIfAborted();
      if (!grant.admitted) throw new Error('The shared program no longer has an active grant');
      const sharedRoot = physicalDirectory(grant.root);
      let workspaceRoot = sharedRoot;
      if (standing.mode !== 'danger-full-access') {
        const standingRoot = physicalDirectory(standing.workspaceRoot);
        if (within(sharedRoot, standingRoot)) workspaceRoot = standingRoot;
        else if (!within(standingRoot, sharedRoot)) throw new Error('Shared PTC workspace does not intersect the standing policy');
      }
      const mode = grant.writable && standing.mode !== 'read-only' ? 'workspace-write' : 'read-only';
      mark('liveshare-ptc-policy', { mode, fork: grant.fork });
      return { mode, workspaceRoot, sessionId: standing.sessionId };
    },
    permissions,
  };
}

// The viewer carrier exposes the ordinary Gateway but the binary route is owner-only.
function installViewerUploads() {
  if (globalThis.__DSH_FILE_UPLOAD__ !== undefined) return;
  const maxBytes = 16 * 1024 * 1024;
  const upload = async (input, init) => {
    const url = new URL(input, document.baseURI);
    if (!url.pathname.endsWith('/api/session/uploadFileBinary')) return fetch(input, init);
    const replyError = (code, message) => Response.json({ ok: false, error: { code, message, details: {} } });
    const sessionId = url.searchParams.get('sessionId');
    const transport = globalThis.__DSH_TRANSPORT__;
    if (!sessionId || !transport) return replyError('file-upload/unavailable', 'The shared upload is unavailable.');
    if (!(init.body instanceof Blob)) return replyError('file-upload/invalid-body', 'Attach a file to upload it.');
    if (init.body.size > maxBytes) {
      return replyError('file-upload/too-large', 'LiveShare attachments are limited to 16 MiB per upload.');
    }
    init.signal?.throwIfAborted();
    const bytes = new Uint8Array(await init.body.arrayBuffer());
    init.signal?.throwIfAborted();
    const pieces = [];
    for (let offset = 0; offset < bytes.length; offset += 16384) {
      pieces.push(String.fromCharCode(...bytes.subarray(offset, offset + 16384)));
    }
    const method = 'fileUploads/upload';
    const request = { data: btoa(pieces.join('')) };
    const name = url.searchParams.get('name');
    const mediaType = url.searchParams.get('mediaType');
    if (name !== null) request.name = name;
    if (mediaType !== null) request.mediaType = mediaType;
    const rpcId = crypto.randomUUID();
    const response = await transport.fetch(new URL('api/' + method, document.baseURI), {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ type: 'client-request', rpcId, method, payload: { args: { agentId: sessionId, request } } }),
      signal: init.signal,
    });
    init.signal?.throwIfAborted();
    const frame = await response.json();
    if (frame.type !== 'server-response' || frame.rpcId !== rpcId || typeof frame.result?.ok !== 'boolean') {
      return replyError('file-upload/unavailable', 'The shared upload received an invalid response.');
    }
    return Response.json(frame.result);
  };
  globalThis.__DSH_FILE_UPLOAD__ = { fetch: upload };
}

function addViewerUploads(answer) {
  if (answer.status !== 200 || !answer.body?.contentType?.startsWith('text/html')) return answer;
  const html = Buffer.from(answer.body.base64, 'base64').toString('utf8');
  const fragment = `<script id="dsh-share-upload">(${installViewerUploads.toString()})();</script>`;
  const updated = html.replace(/<head(?:\s[^>]*)?>/i, head => head + fragment);
  if (html === updated) return answer;
  return { ...answer, body: { ...answer.body, base64: Buffer.from(updated).toString('base64') } };
}

function patchFileUploads(source, replacePinned) {
  return replacePinned(source, 'async upload(agent, request, signal) {', `async upload(agent, request, signal) {
    if (request.mediaType !== undefined) {
      signal.throwIfAborted();
      const limits = this.ctx.attachments.imageLimits;
      const max = Math.min(limits.maxImageBytes, limits.maxMessageImageBytes);
      const invalid = (message, reason) => new RemoteError("session/attachment-invalid", message, { reason });
      if (request.data.length > Math.ceil(max / 3) * 4) {
        throw invalid("The shared image exceeds the upload limit.", "IMAGE_TOO_LARGE");
      }
      const bytes = Buffer.from(request.data, "base64");
      if (bytes.toString("base64") !== request.data) {
        throw invalid("The shared image has an invalid encoding.", "INVALID_IMAGE_BASE64");
      }
      return this.uploadImageStream({
        sessionId: agent.id, mediaType: request.mediaType, name: request.name, signal,
        data: (async function* () { yield bytes; })(),
      });
    }`);
}

function patchFileUploadSchemas(source, replacePinned) {
  const requestField = "  'data': z.string().readonly().describe('Canonical base64 encoding of the exact file bytes.'),";
  if (source.split(requestField).length !== 3) throw new Error('Unexpected pinned FileUploads arguments');
  const withMediaType = source.replaceAll(requestField, requestField + "\n  'mediaType': z.string().readonly().optional(),");
  const resultStart = "upload_result$schema$value ??= z.object({";
  const resultEnd = "\n}))\nlet _deepseek_ai_dsh_client_file_upload_fileUploads_upload_parameter_0_strict";
  const union = `
}), z.object({
  receiptId: z.string(),
  image: z.object({
    attachmentId: z.string(), mediaType: z.string(), bytes: z.number(),
    width: z.number(), height: z.number(), name: z.string().optional(),
    originalDimensions: z.object({ width: z.number(), height: z.number() }).optional(),
  }),
})]))
let _deepseek_ai_dsh_client_file_upload_fileUploads_upload_parameter_0_strict`;
  let patched = replacePinned(withMediaType, resultStart, "upload_result$schema$value ??= z.union([z.object({");
  patched = replacePinned(patched, resultEnd, union);
  const requestSchema = /jsonSchema: (\{"type":"object","properties":\{"data".*"required":\["data"\].*\}),/g;
  if (Array.from(patched.matchAll(requestSchema)).length !== 2) throw new Error('Unexpected pinned FileUploads request metadata');
  patched = patched.replace(requestSchema, (_row, json) => {
    const schema = JSON.parse(json);
    schema.properties.mediaType = { type: 'string' };
    return 'jsonSchema: ' + JSON.stringify(schema) + ',';
  });
  const resultSchema = /jsonSchema: (\{"type":"object","properties":\{"receiptId".*"required":\["receiptId","file"\].*\}),/;
  const match = patched.match(resultSchema);
  if (!match) throw new Error('Unexpected pinned FileUploads result metadata');
  const image = {
    type: 'object',
    properties: {
      attachmentId: { type: 'string' }, mediaType: { type: 'string' }, bytes: { type: 'number' },
      width: { type: 'number' }, height: { type: 'number' }, name: { type: 'string' },
      originalDimensions: { type: 'object', properties: { width: { type: 'number' }, height: { type: 'number' } },
        required: ['width', 'height'] },
    },
    required: ['attachmentId', 'mediaType', 'bytes', 'width', 'height'],
  };
  const result = { anyOf: [JSON.parse(match[1]), {
    type: 'object', properties: { receiptId: { type: 'string' }, image }, required: ['receiptId', 'image'],
  }] };
  return replacePinned(patched, match[0], 'jsonSchema: ' + JSON.stringify(result) + ',');
}

function createTunnelLauncher(entry, mark) {
  return (_executable, args, { env, stdio }) => {
    if (args.length !== 1 || args[0] !== entry || stdio.join(',') !== 'ignore,pipe,pipe,ipc') {
      throw new Error('Unexpected Harmony LiveShare gateway launch');
    }
    const worker = new Worker(__filename, {
      name: 'dsh-liveshare-gateway', execArgv: [], stdout: true, stderr: true,
      env: Object.fromEntries(Object.entries(env).filter(([, value]) => value !== undefined)),
      workerData: { entry },
    });
    const { threadId } = worker;
    const child = Object.assign(new EventEmitter(), {
      connected: true, exitCode: null, signalCode: null,
      stdout: worker.stdout, stderr: worker.stderr,
      send(message) {
        if (!child.connected) return false;
        worker.postMessage(message);
        return true;
      },
      kill(signal) {
        if (!child.connected) return false;
        child.connected = false;
        child.signalCode = signal;
        worker.terminate().catch(error => child.emit('error', error));
        return true;
      },
    });
    mark('liveshare-worker-started', { threadId });
    worker.once('online', () => child.emit('spawn'));
    worker.on('message', message => child.emit('message', message));
    worker.once('error', error => {
      child.connected = false;
      child.emit('error', error);
    });
    worker.once('exit', code => {
      child.connected = false;
      if (child.signalCode === null) child.exitCode = code;
      mark('liveshare-worker-stopped', { threadId, code });
      child.emit('exit', child.exitCode, child.signalCode);
    });
    return child;
  };
}

if (isMainThread) {
  module.exports = { createTunnelLauncher, createSharedPtcPolicy, addViewerUploads, patchFileUploads, patchFileUploadSchemas };
} else {
  // Keep the packaged gateway's IPC message contract on an isolated Node thread.
  process.send = message => {
    parentPort.postMessage(message);
    return true;
  };
  parentPort.on('message', message => process.emit('message', message));
  parentPort.once('close', () => process.emit('disconnect'));
  import(pathToFileURL(workerData.entry).href).catch(error => {
    console.error(error);
    process.exit(1);
  });
}
