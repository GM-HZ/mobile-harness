"""Verify RC.5 Inspector CDP over the authenticated ArkWeb Host proxy."""
import argparse
import hashlib
import json
from pathlib import Path
import runpy
import socket
import subprocess
import urllib.error
import urllib.request
from urllib.parse import urlsplit
import uuid

market = runpy.run_path(str(Path(__file__).with_name('emulator-plugin-market.py')))
approval = runpy.run_path(str(Path(__file__).with_name('emulator-ptc-approval.py')))
probe = runpy.run_path(str(Path(__file__).with_name('emulator-inspector-availability.py')))
support, agent, lsp = (market[key] for key in ['support', 'agent', 'lsp'])
NAME, PROFILE, request = (probe[key] for key in ['NAME', 'PROFILE', 'request'])
BOOTSTRAP = '/api/experimental-inspector/bootstrap'
ASSET = '/inspector/devtools/devtools_app.html'


def catalog(emulator, enabled):
    row = market['catalog'](emulator, NAME)
    assert row and row['availability'] == 'installation' and row['optional'] and row['official'], row
    assert not row['removable'] and not row.get('error') and row['enabled'] == enabled, row
    return {key: row[key] for key in ['availability', 'enabled', 'optional', 'official', 'version']}


def cdp(emulator):
    assert request(emulator, BOOTSTRAP, False)[0] == 401
    status, body = request(emulator, BOOTSTRAP, True)
    if status != 200:
        fibers = [{k: row.get(k) for k in ['fiberPhase', 'diagnostic']}
                  for row in emulator.rpc('pluginManager/listPlugins', {})
                  if row['moduleName'] == '@deepseek-ai/dsh-experimental-inspector']
        raise AssertionError((status, fibers))
    info = json.loads(body)
    target = urlsplit(info['endpoint'])
    assert (target.scheme, target.hostname, target.path) == ('ws', '127.0.0.1', '/ingest')
    status, html = request(emulator, ASSET, True)
    assert status == 200 and b'devtools_app' in html, status
    assert request(emulator, ASSET, False)[0] == 401

    forward = ('tcp:19645', f'tcp:{target.port}')
    assert 'Forwardport result:OK' in emulator.hdc('fport', *forward)
    try:
        direct = 'http://127.0.0.1:19645/json/list'
        try:
            emulator.opener.open(direct, timeout=4)
        except urllib.error.HTTPError as error:
            assert error.code == 403
        else:
            raise AssertionError('Anonymous direct discovery should be refused')
        discovery = urllib.request.Request(direct, headers={'X-DSH-Inspector-Token': info['protocol']})
        with emulator.opener.open(discovery, timeout=4) as response:
            targets = json.load(response)
        assert len(targets) == 1
        page = urlsplit(targets[0]['webSocketDebuggerUrl'])
        assert (page.scheme, page.hostname, page.port) == ('ws', '127.0.0.1', target.port)
        payload = {'proxy': emulator.url.replace('http:', 'ws:') + '/inspector/devtools/cdp',
                   'direct': 'ws://127.0.0.1:19645' + page.path,
                   'cookie': emulator.cookie()}
        node = '/Applications/DevEco-Studio.app/Contents/tools/node/bin/node'
        fixture = Path(__file__).with_name('fixtures') / 'inspector-cdp.cjs'
        result = subprocess.check_output([node, str(fixture), str(approval['ws_module']())],
                                         input=json.dumps(payload), text=True, timeout=25)
        return {'workerPort': target.port, 'anonymousDiscoveryStatus': 403, 'targetCount': len(targets),
                'devtoolsAssetSha256': hashlib.sha256(html).hexdigest(), **json.loads(result)}
    finally:
        emulator.hdc('fport', 'rm', *forward)


def run(emulator, output):
    evidence, originals = {}, {}
    remote = '/data/local/tmp/mh-inspector-' + uuid.uuid4().hex
    try:
        emulator.ready('normal')
        evidence['defaultCatalog'] = catalog(emulator, False)
        assert request(emulator, BOOTSTRAP, True)[0] == 404
        for path in [PROFILE+'/package.json', PROFILE+'/pnpm-lock.yaml', 'mobile-harness-boot.json']:
            originals[path] = agent['read_bytes'](emulator, path)
        for enabled in [True, False]:
            result = emulator.rpc('pluginManager/setBundleEnabled', {'name': NAME, 'enabled': enabled})
            assert result['application'] in ['applied', 'restart-required'], result
            evidence['enable' if enabled else 'disable'] = result['application']
            if enabled or result['application'] == 'restart-required':
                emulator.stop()
                emulator.start()
                emulator.ready('normal')
            catalog(emulator, enabled)
            if enabled:
                evidence['cdp'] = cdp(emulator)
            else:
                assert request(emulator, BOOTSTRAP, True)[0] == 404
                port = evidence['cdp']['workerPort']
                forward = ('tcp:19645', f'tcp:{port}')
                assert 'Forwardport result:OK' in emulator.hdc('fport', *forward)
                try:
                    with socket.create_connection(('127.0.0.1', 19645), timeout=3) as connection:
                        connection.settimeout(3)
                        connection.sendall(b'GET /json/list HTTP/1.0\r\n\r\n')
                        assert not connection.recv(1), 'Disabled Worker kept serving its port'
                except (ConnectionRefusedError, ConnectionResetError):
                    pass
                finally:
                    emulator.hdc('fport', 'rm', *forward)
                evidence['workerReleasedOnDisable'] = True
    finally:
        try:
            if originals:
                emulator.stop()
                for index, (path, body) in enumerate(originals.items()):
                    lsp['restore_bytes'](emulator, path, body, remote + str(index))
                emulator.start()
                evidence['restoredReadyMs'] = emulator.ready('normal')
                for path, body in originals.items():
                    assert agent['read_bytes'](emulator, path) == body
                evidence['restoredConfiguration'] = True
        finally:
            output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + '\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('target')
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    emulator = support['Emulator'](args.target, 19643)
    forward = ('tcp:19643', 'tcp:19592')
    assert 'Forwardport result:OK' in emulator.hdc('fport', *forward)
    try:
        run(emulator, args.output)
    finally:
        emulator.hdc('fport', 'rm', *forward)
