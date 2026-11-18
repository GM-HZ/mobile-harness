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
  module.exports = { createTunnelLauncher, createSharedPtcPolicy };
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
