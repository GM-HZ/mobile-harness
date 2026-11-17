"""Cancel a real streamed compaction via HTTP disconnect; verify busy/failure recovery."""
import argparse
from contextlib import contextmanager
import hashlib
import http.client
import io
import json
import os
from pathlib import Path
import runpy
import socket
import tarfile
import tempfile
import time
from urllib.parse import urlsplit
import uuid

compact = runpy.run_path(str(Path(__file__).with_name('emulator-compaction.py')))
agent = compact['agent']; support = compact['support']
lsp = runpy.run_path(str(Path(__file__).with_name('emulator-lsp-lifecycle.py')))
PROFILE = 'alpine/native-benchmark-home/profiles/web'


@contextmanager
def fault_bundle(emulator, evidence):
    name = 'mh-compaction-fault-' + uuid.uuid4().hex[:10]
    app = 'alpine/workspace-native/' + name; path = support['WORKSPACE'] + '/' + name
    remote = '/data/local/tmp/' + name
    originals = {}
    evidence['fixture'] = name
    try:
        emulator.ready('normal')
        assert emulator.app('test ! -e alpine/native-benchmark-home/cordis.patch.yml && printf EMPTY') == 'EMPTY'
        for file in [PROFILE + '/package.json', PROFILE + '/pnpm-lock.yaml', 'mobile-harness-boot.json']:
            originals[file] = agent['read_bytes'](emulator, file)
            if file.endswith('.json'): json.loads(originals[file])
        evidence['originalHashes'] = {file: hashlib.sha256(body).hexdigest() for file, body in originals.items()}
        source = Path(__file__).with_name('fixtures').joinpath('compaction-stream-fault.mjs').read_text()
        source = source.replace('__MH_WORKSPACE__', json.dumps(path))
        files = {'package.json': json.dumps({'name': name, 'version': '1.0.0', 'type': 'module', 'main': 'index.js',
                  'files': ['index.js', 'cordis.patch.yml'], 'dsh': {'bundle': {'patch': './cordis.patch.yml'}}}),
                 'cordis.patch.yml': f'- insert:\n    - id: {name}\n      name: {name}\n', 'index.js': source}
        with tempfile.TemporaryDirectory() as folder:
            archive = Path(folder) / 'bundle.tgz'
            with tarfile.open(archive, 'w:gz', format=tarfile.USTAR_FORMAT) as packed:
                for file, text in files.items():
                    body = text.encode(); info = tarfile.TarInfo(file); info.size = len(body); packed.addfile(info, io.BytesIO(body))
            assert 'FileTransfer finish' in emulator.hdc('file', 'send', str(archive), remote + '.tgz')
            assert emulator.app(f'mkdir {app} && tar -xzf {remote}.tgz -C {app} && printf READY') == 'READY'
        installed = emulator.rpc('pluginManager/installBundle', {'spec': 'file:' + path, 'options': {'enabled': False}}, timeout=90)
        assert installed.get('enabled') is False and installed['application'] != 'failed', installed
        enabled = emulator.rpc('pluginManager/setBundleEnabled', {'name': name, 'enabled': True})
        assert enabled['application'] != 'failed', enabled
        emulator.stop(); emulator.start(); evidence['fixtureReadyMs'] = emulator.ready('normal')
        yield app, path
        removed = emulator.rpc('pluginManager/removeBundle', {'name': name}, timeout=90)
        assert removed['application'] != 'failed' and removed['packageResult']['exitCode'] == 0, removed
        evidence['fixtureRemovedThroughPluginManager'] = True
    finally:
        try:
            if originals:
                emulator.stop()
                for index, (file, body) in enumerate(originals.items()):
                    lsp['restore_bytes'](emulator, file, body, remote + '-restore-' + str(index))
                emulator.app(f'rm -rf {app} {PROFILE}/node_modules/{name}')
                emulator.start(); evidence['restoredReadyMs'] = emulator.ready('normal')
                evidence['restoredHashes'] = {file: hashlib.sha256(agent['read_bytes'](emulator, file)).hexdigest() for file in originals}
                assert evidence['originalHashes'] == evidence['restoredHashes']
        finally: emulator.hdc('shell', 'rm', '-f', remote + '.tgz')


def control(emulator, app, session_id, action):
    body = (json.dumps({'sessionId': session_id, 'action': action}) + '\n').encode()
    lsp['restore_bytes'](emulator, app + '/control.json', body, '/data/local/tmp/mh-compaction-control-' + uuid.uuid4().hex)


def seed(emulator, sid, path, marker, action):
    filler = '\n'.join(f'Archived row {i}: checksum {hashlib.sha256(str(i).encode()).hexdigest()}, observation passed, no remaining work.' for i in range(180))
    calls, _, _ = agent['prompt'](emulator, sid,
        'For this owned compaction fixture, remember this essential exact label for later recall: ' + marker
        + '. Do not save the label to disk or call tools. The following completed observations are disposable. '
        'Acknowledge only.\n<archived>\n' + filler + '\n</archived>')
    assert not calls
    payload = 'UNRELATED_' + uuid.uuid4().hex
    agent['tool'](emulator, sid, 'write', {'file_path': path + '/pair-' + action + '.txt', 'content': payload})
    agent['tool'](emulator, sid, 'read', {'file_path': path + '/pair-' + action + '.txt'})


def failed_transaction(emulator, sid, before, command_id):
    deadline = time.monotonic() + 12
    while time.monotonic() < deadline:
        rows = support['events'](emulator, sid)
        starts = [r for r in rows if r['type'] == 'compaction/start' and r['data'].get('sourceCommandId') == command_id]
        ends = [r for r in rows if r['type'] == 'compaction/end' and r['data'].get('sourceCommandId') == command_id]
        if ends:
            assert len(starts) == len(ends) == 1 and starts[0]['data']['compactionId'] == ends[0]['data']['compactionId']
            assert ends[0]['data']['error'], ends
            assert not any(r['type'] == 'compaction/summary' and r['data'].get('sourceCommandId') == command_id for r in rows)
            old = {r['seq']: r for r in before}; current = {r['seq']: r for r in rows}
            assert all(current[seq] == row for seq, row in old.items())
            assert not any(r['type'] == 'user/message' and r['data'].get('source', {}).get('compactionId') == starts[0]['data']['compactionId'] for r in rows)
            return {'start': starts[0], 'end': ends[0], 'noSummaryOrCheckpointCommitted': True}
        time.sleep(.1)
    raise AssertionError('Compaction did not close its failed transaction')


def cancelled_request(emulator, sid, app, before):
    target = urlsplit(emulator.url)
    client = http.client.HTTPConnection(target.hostname, target.port, timeout=5)
    request_id = str(uuid.uuid4())
    body = json.dumps({'type': 'client-request', 'rpcId': request_id, 'method': 'commands/execute',
                       'payload': {'args': {'agentId': sid, 'line': '/compact', 'submittedAttachments': []}}})
    command_id = None; result = {}
    try:
        client.request('POST', '/api/commands/execute', body=body,
                       headers={'Content-Type': 'application/json', 'Host': '127.0.0.1:19592', 'Cookie': emulator.cookie()})
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            if emulator.app('test -f ' + app + '/cancel-observed.json && printf OBSERVED') == 'OBSERVED':
                result['observedRealProviderChunk'] = json.loads(emulator.app('cat ' + app + '/cancel-observed.json'))
                rows = support['events'](emulator, sid)
                runs = [r for r in rows if r['type'] == 'command/run' and r['seq'] > before[-1]['seq']]
                assert len(runs) == 1, runs
                command_id = runs[0]['data']['commandId']; break
            time.sleep(.05)
        assert command_id, 'Must observe genuine streamed model output before cancelling'
        busy = emulator.rpc('commands/execute', {'agentId': sid, 'line': '/compact', 'submittedAttachments': []}, timeout=8)
        assert busy['result']['kind'] == 'error' and 'active compaction' in busy['result']['text'], busy
        result['concurrentRequestRejected'] = busy
        assert client.sock is not None
        started = time.monotonic(); client.sock.shutdown(socket.SHUT_RDWR); client.close()
        result['cancelled'] = failed_transaction(emulator, sid, before, command_id)
        result['disconnectToSettledMs'] = round((time.monotonic() - started) * 1000)
        return result
    finally: client.close()


def run(emulator, output):
    evidence = {}; sid = None; unfinished = False
    try:
        with fault_bundle(emulator, evidence) as (app, path):
            with support['model_key'](emulator):
                try:
                    for action in ['cancel', 'failure']:
                        marker = 'FACT_' + uuid.uuid4().hex.upper()
                        sid = support['session'](emulator, True); unfinished = True
                        seed(emulator, sid, path, marker, action); unfinished = False
                        control(emulator, app, sid, action)
                        before = support['events'](emulator, sid)
                        if action == 'cancel':
                            case = cancelled_request(emulator, sid, app, before)
                        else:
                            execution = compact['command'](emulator, sid, '/compact')
                            assert execution['result']['kind'] == 'error' and 'useful summary' in execution['result']['text'], execution
                            case = {'failure': failed_transaction(emulator, sid, before, execution['commandId']),
                                    'observedRealProviderChunk': json.loads(emulator.app('cat ' + app + '/failure-observed.json'))}
                        control(emulator, app, None, 'normal')
                        before_retry = support['events'](emulator, sid)
                        execution = compact['command'](emulator, sid, '/compact')
                        case['successfulRetry'] = compact['verify_transaction'](before_retry, support['events'](emulator, sid), execution)
                        cutoff = max(r['seq'] for r in support['events'](emulator, sid)); unfinished = True
                        calls, _, rows = agent['prompt'](emulator, sid, 'Recall the essential exact fixture label given earlier. Reply only with that label. No tools or file reads.')
                        assert not calls
                        reply = agent['assistant_texts']([r for r in rows if r['seq'] > cutoff]).strip()
                        assert reply == marker, reply
                        case['exactRecallAfterRetry'] = reply; unfinished = False
                        evidence[action] = case; sid = None
                        print(action, 'passed', flush=True)
                finally:
                    if sid and unfinished:
                        emulator.rpc('session/cancel', {'request': {'sessionId': sid}})
                        unfinished = False
            evidence['temporaryModelCredentialRemoved'] = True
    finally:
        output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + '\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('target'); parser.add_argument('output', type=Path); options = parser.parse_args()
    if not os.environ.get('MH_TEST_DEEPSEEK_API_KEY'): parser.error('MH_TEST_DEEPSEEK_API_KEY is required')
    emulator = support['Emulator'](options.target, 19643); forward = ('tcp:19643', 'tcp:19592')
    emulator.hdc('fport', *forward)
    try: run(emulator, options.output)
    finally: emulator.hdc('fport', 'rm', *forward)
