"""Probe the optional diagnostic Inspector Worker; availability is not full CDP acceptance."""
import argparse
import hashlib
import json
from pathlib import Path
import runpy
import urllib.error
import urllib.request
import uuid

agent = runpy.run_path(str(Path(__file__).with_name('emulator-agent-continuation.py')))
support = agent['support']
lsp = runpy.run_path(str(Path(__file__).with_name('emulator-lsp-lifecycle.py')))
PROFILE = 'alpine/native-benchmark-home/profiles/web'
NAME = '@deepseek-ai/dsh-experimental-inspector-profile'


def request(emulator, path, authenticated):
    headers = {'Host': '127.0.0.1:19592'}
    if authenticated: headers['Cookie'] = emulator.cookie()
    req = urllib.request.Request(emulator.url + path, headers=headers)
    try:
        with emulator.opener.open(req, timeout=15) as response: return response.status, response.read()
    except urllib.error.HTTPError as error: return error.code, error.read()


def run(emulator, output):
    evidence = {'bundle': NAME, 'fullDiagnosticCdpVerified': False}; originals = {}; remote = '/data/local/tmp/mh-inspector-' + uuid.uuid4().hex
    try:
        emulator.ready('normal')
        assert not emulator.rpc('credentials/describe', {'refs': ['DEEPSEEK_API_KEY']})['DEEPSEEK_API_KEY']['configured']
        for path in [PROFILE + '/package.json', PROFILE + '/pnpm-lock.yaml', 'mobile-harness-boot.json']:
            originals[path] = agent['read_bytes'](emulator, path)
            if path.endswith('.json'): json.loads(originals[path])
        manifest = json.loads(originals[PROFILE + '/package.json'])
        bundles = manifest['dsh']['profile']['bundles']
        assert NAME not in bundles, 'Do not alter an already user-configured Inspector'
        # Installed packages are not automatically discoverable as root bundles.
        # Compose this optional official bundle just like the Ralph regression;
        # restore the original bytes rather than inventing a management catalog.
        manifest['dsh']['profile']['bundles'] = bundles + [NAME]
        emulator.stop()
        lsp['restore_bytes'](emulator, PROFILE + '/package.json', (json.dumps(manifest) + '\n').encode(), remote + '-mount')
        emulator.start(); evidence['readyMs'] = emulator.ready('normal')
        row = next(row for row in emulator.rpc('pluginManager/listBundles', {}) if row['name'] == NAME)
        assert row['enabled'] is True, row
        evidence['temporarilyComposedOfficialBundle'] = True
        evidence['liveEntries'] = [row for row in emulator.rpc('pluginManager/listPlugins', {})
                                  if row.get('moduleName') in ['@deepseek-ai/dsh-experimental-inspector', '@deepseek-ai/dsh-experimental-session-inspector', '@deepseek-ai/dsh-experimental-client-ui-stats']]
        evidence['anonymousBootstrapStatus'] = request(emulator, '/api/experimental-inspector/bootstrap', False)[0]
        assert evidence['anonymousBootstrapStatus'] == 401
        status, body = request(emulator, '/api/experimental-inspector/bootstrap', True)
        evidence['authenticatedBootstrapStatus'] = status
        if status == 200:
            bootstrap = json.loads(body)
            # Do not persist the Worker ingest protocol token or the browser cookie.
            evidence['bootstrapKeys'] = sorted(bootstrap)
            evidence['workerAvailable'] = True
            asset_status, asset = request(emulator, '/inspector/devtools/devtools_app.html', True)
            evidence['devtoolsAsset'] = {'status': asset_status, 'bytes': len(asset), 'sha256': hashlib.sha256(asset).hexdigest()}
        elif status == 503:
            evidence['workerAvailable'] = False
        else: raise AssertionError(f'Unexpected Inspector bootstrap status {status}')
        evidence['disable'] = emulator.rpc('pluginManager/setBundleEnabled', {'name': NAME, 'enabled': False})
        assert evidence['disable']['application'] != 'failed'
    finally:
        try:
            if originals:
                emulator.stop()
                for index, (path, body) in enumerate(originals.items()): lsp['restore_bytes'](emulator, path, body, remote + str(index))
                emulator.start(); evidence['restoredReadyMs'] = emulator.ready('normal')
                evidence['configurationHashesRestored'] = {path: hashlib.sha256(agent['read_bytes'](emulator, path)).hexdigest() for path in originals}
                assert evidence['configurationHashesRestored'] == {path: hashlib.sha256(body).hexdigest() for path, body in originals.items()}
                assert not emulator.rpc('credentials/describe', {'refs': ['DEEPSEEK_API_KEY']})['DEEPSEEK_API_KEY']['configured']
                evidence['testCredentialAbsentThroughout'] = True
        finally: output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + '\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('target'); parser.add_argument('output', type=Path); options = parser.parse_args()
    emulator = support['Emulator'](options.target, 19643); forward = ('tcp:19643', 'tcp:19592')
    emulator.hdc('fport', *forward)
    try: run(emulator, options.output)
    finally: emulator.hdc('fport', 'rm', *forward)
