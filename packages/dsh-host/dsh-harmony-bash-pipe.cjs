'use strict';

const path = require('node:path');
const { randomUUID } = require('node:crypto');

const MAX_CHARS = 128 * 1024;
const fences = new WeakSet();

function appendBounded(target, value) {
  target.text += value;
  if (target.text.length <= MAX_CHARS) return;
  target.text = target.text.slice(-MAX_CHARS);
  if (/^[\uDC00-\uDFFF]/u.test(target.text)) target.text = target.text.slice(1);
  target.truncated = true;
}

class BashPipeSession {
  constructor(handle, marker, authorized, onClose, TerminalError) {
    this.handle = handle;
    this.motd = '';
    this.marker = marker;
    this.authorized = authorized;
    this.onClose = onClose;
    this.TerminalError = TerminalError;
    this.buffer = '';
    this.retained = { text: '', truncated: false };
    this.current = { kind: 'running' };
    this.active = undefined;
    this.closing = undefined;
    handle.stdout.setEncoding('utf8');
    handle.stdout.on('data', data => this.receive(data));
    handle.stderr.setEncoding('utf8');
    handle.stderr.on('data', data => this.append(data));
    for (const stream of [handle.stdin, handle.stdout, handle.stderr]) {
      stream.on('error', error => this.fail(error));
    }
    handle.done.then(outcome => {
      this.current = { kind: 'exited', ...outcome };
      this.append(this.buffer);
      this.buffer = '';
      this.settle('session_exit');
    }, error => this.fail(error));
  }

  append(value) {
    appendBounded(this.retained, value);
    if (this.active) {
      appendBounded(this.active, value);
      appendBounded(this.active.unread, value);
    }
  }

  receive(data) {
    this.buffer += data;
    for (;;) {
      const end = this.buffer.indexOf(this.marker);
      if (end < 0) break;
      this.append(this.buffer.slice(0, end));
      this.buffer = this.buffer.slice(end + this.marker.length);
      this.settle('stdin_read');
    }
    const ready = this.buffer.length - this.marker.length + 1;
    if (ready > 0) {
      this.append(this.buffer.slice(0, ready));
      this.buffer = this.buffer.slice(ready);
    }
  }

  fail(error) {
    const active = this.active;
    if (!active) return;
    this.active = undefined;
    active.signal?.removeEventListener('abort', active.abort);
    active.reject(error);
  }

  settle(waitReason) {
    const active = this.active;
    if (!active) return;
    this.active = undefined;
    active.signal?.removeEventListener('abort', active.abort);
    active.resolve({ viewport: active.text, truncated: active.truncated, waitReason, sessionStatus: this.current });
  }

  status() {
    return this.current;
  }

  startSend({ text, submit, signal }) {
    signal?.throwIfAborted();
    if (!this.authorized()) {
      void this.close().catch(error => this.fail(error));
      throw new this.TerminalError('Persistent Bash requires a sandbox backend for the current permission mode', 'NO_SANDBOX');
    }
    if (this.active) throw new this.TerminalError('Persistent Bash is already running a command', 'BUSY');
    if (!submit || /[\r\n\0]/u.test(text)) {
      throw new this.TerminalError('Persistent Bash expects a single framed, non-interactive command', 'INVALID_INPUT');
    }
    if (this.closing || this.current.kind === 'exited') {
      return { done: Promise.resolve({ viewport: '', truncated: false, waitReason: 'session_exit', sessionStatus: this.current }),
        readOutput: () => ({ delta: '', truncated: false }), cancel: () => false };
    }
    const { promise: done, resolve, reject } = Promise.withResolvers();
    const unread = { text: '', truncated: false };
    const operation = { text: '', truncated: false, unread, resolve, reject, signal, abort: () => {
      void this.close().catch(error => this.fail(error));
    } };
    this.active = operation;
    signal?.addEventListener('abort', operation.abort, { once: true });
    const command = text === 'stty -echo; set +H' ? 'set +H' : text;
    this.handle.stdin.write(command + '\n', error => { if (error) this.fail(error); });
    return {
      done,
      readOutput: () => {
        const output = { delta: unread.text, truncated: unread.truncated };
        unread.text = '';
        unread.truncated = false;
        return output;
      },
      cancel: () => {
        if (this.active !== operation) return false;
        operation.abort();
        return true;
      },
    };
  }

  read({ offset = 0, count = 1000 }) {
    const lines = this.retained.text === '' ? [] : this.retained.text.split('\n');
    const end = Math.max(0, lines.length - offset);
    const start = Math.max(0, end - Math.min(count, 1000));
    return { text: lines.slice(start, end).join('\n'), totalLines: lines.length,
      lineBegin: lines.length - end, lineEnd: lines.length - start, truncated: this.retained.truncated };
  }

  async signal() {
    throw new this.TerminalError('Persistent Bash pipes have no terminal foreground group', 'FOREGROUND_UNAVAILABLE');
  }

  close() {
    this.closing ??= (async () => {
      this.handle.terminate();
      if (!await this.handle.waitForExit()) throw new Error('Persistent Bash process range did not exit');
      await this.handle.done;
      this.onClose();
    })();
    return this.closing;
  }
}

function registerBashPipe(ctx, type, root, TerminalError, mark) {
  ctx.terminals.registerBackend({
    type,
    async spawn(spec) {
      const owner = spec.owner;
      const policy = () => ctx.sandboxPolicy.resolve({ session: owner.session }).mode;
      if (policy() !== 'danger-full-access') {
        throw new TerminalError('Persistent Bash requires a sandbox backend for the current permission mode', 'NO_SANDBOX');
      }
      if (!fences.has(owner)) {
        fences.add(owner);
        owner.ctx.on('internal/dispatch', (_mode, event, args) => {
          if (event !== 'session/event') return;
          const [session, row] = args;
          if (session === owner.session && row.type === 'sandbox/mode' &&
              row.data.mode !== policy() && ctx.terminals.hasOwnerActivity(owner)) {
            throw new TerminalError('Close persistent Bash before changing its permission mode', 'ACTIVE_SESSION');
          }
        }, { global: true });
      }
      const cwd = spec.cwd ?? await ctx.workingDirectory.ensure(owner, spec.signal);
      spec.signal?.throwIfAborted();
      const nonce = randomUUID();
      const marker = '\x1e' + nonce + '\x1f';
      const loop = [
        'exec 2>&1',
        'while IFS= read -r __mh_bash_line; do',
        '  eval -- "$__mh_bash_line" </dev/null',
        "  builtin printf '\\036%s\\037' " + nonce,
        'done',
      ].join('\n');
      const handle = ctx.subprocess.spawn({
        argv: [path.join(root, 'bin/bash'), '--noprofile', '--norc', '-c', loop],
        cwd, stdio: { stdin: 'pipe', stdout: 'pipe', stderr: 'pipe' },
        env: { TERM: 'dumb', PAGER: 'cat', GIT_PAGER: 'cat' },
        graceMs: 1000,
      });
      if (!handle.stdin || !handle.stdout || !handle.stderr) {
        handle.terminate();
        await handle.waitForExit();
        throw new TerminalError('Persistent Bash did not receive its required pipes', 'INIT_REJECTED');
      }
      const fields = { id: spec.sessionId };
      mark('persistent-bash-started', fields);
      return new BashPipeSession(handle, marker, () => policy() === 'danger-full-access',
        () => mark('persistent-bash-reaped', fields), TerminalError);
    },
  });
}

module.exports = { registerBashPipe };
