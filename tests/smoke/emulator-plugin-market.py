"""Verify the official market against an owned npm registry and real DSH plugin updates."""
import argparse
import base64
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
from itertools import groupby
import json
import os
from pathlib import Path
import runpy
import tarfile
import threading
from urllib.parse import urlsplit
import uuid

flow = runpy.run_path(str(Path(__file__).with_name('emulator-chat-import.py')))
agent, support, lsp = (flow[key] for key in ['agent', 'support', 'lsp'])
PROFILE = flow['PROFILE']
BUNDLE = '@deepseek-ai/dsh-experimental-plugin-market-bundle'
VERSIONS = ('1.0.0', '1.1.0', '1.2.0', '2.0.0')
STAMP = '2024-01-01T00:00:00.000Z'
DEVICE_PORT = 19742


class Registry(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def do_GET(self):
        path = urlsplit(self.path).path
        self.server.requests.append(path)
        body, content_type = self.server.responses.get(path, (None, None))
        if body is None:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def tarball(files):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode='w:gz', format=tarfile.USTAR_FORMAT) as archive:
        for name, data in files.items():
            contents = data.encode()
            entry = tarfile.TarInfo('package/' + name)
            entry.size = len(contents)
            archive.addfile(entry, io.BytesIO(contents))
    return buffer.getvalue()


def json_body(value):
    return json.dumps(value).encode(), 'application/json'


def register_release(server, manifest, files):
    name, version = manifest['name'], manifest['version']
    archive = tarball({'package.json': json.dumps(manifest), **files})
    path = f'/{name}/-/{name}-{version}.tgz'
    server.responses[path] = (archive, 'application/octet-stream')
    return {**manifest, 'dist': {'tarball': server.base+path,
            'shasum': hashlib.sha1(archive).hexdigest(),
            'integrity': 'sha512-'+base64.b64encode(hashlib.sha512(archive).digest()).decode()}}


def registry_record(name, releases, latest):
    return {'name': name, 'dist-tags': {'latest': latest}, 'versions': releases,
            'time': {'created': STAMP, 'modified': STAMP, **dict.fromkeys(releases, STAMP)}}


def plugin_source(version, dependency, marker, module_path):
    # A deliberate activation error tests the real PluginManager rollback.
    setup = 'throw new Error("Owned fixture refused activation");' if version == '1.2.0' else ''
    return f'''
import {{ appendFileSync }} from 'node:fs';
import {{ defineTool }} from {json.dumps(module_path)};
import {{ token }} from {json.dumps(dependency)};
export const name = 'mh-market-probe';
export const inject = ['tools'];
export function apply(ctx) {{
  appendFileSync({json.dumps(marker)}, {json.dumps('start ' + version + chr(10))});
  {setup}
  ctx.effect(() => () => appendFileSync({json.dumps(marker)}, {json.dumps('stop ' + version + chr(10))}));
  ctx.tools.register(defineTool({{
    name: 'mh_market_probe',
    description: 'Return the owned plugin version and its installed dependency fingerprint.',
    parameters: {{ marker: {{ type: 'string', required: true, description: 'Exact probe marker to return.' }} }},
    output: {{
      schema: {{ type: 'object', additionalProperties: true, properties: {{}} }},
      render(_args, value) {{ return [{{ type: 'text', text: JSON.stringify(value) }}]; }},
    }},
    execute(args) {{ return {{ version: {json.dumps(version)}, dependency: token, marker: args.marker }}; }},
  }}));
}}
'''


def populate(server, name, root, workspace):
    dependency = name + '-dep'
    settings = {'name': dependency, 'version': '1.0.0', 'type': 'module', 'main': './index.mjs'}
    dep = register_release(server, settings, {'index.mjs': 'export const token = "OWNED_DEPENDENCY_LOADED";\n'})
    server.responses['/'+dependency] = json_body(registry_record(dependency, {'1.0.0': dep}, '1.0.0'))

    module_path = 'file://' + root + '/.dsh-0.2.2-rc.5/dsh/node_modules/@deepseek-ai/dsh-tools/lib/index.js'
    built = {}
    for version in VERSIONS:
        manifest = {'name': name, 'version': version, 'type': 'module', 'main': './index.mjs',
                    'exports': {'.': './index.mjs', './candidate': './candidate.mjs'},
                    'description': 'Owned HarmonyOS plugin registry fixture',
                    'engines': {'dsh': '>=99.0.0' if version == '2.0.0' else '*'},
                    'dsh': {'bundle': {'patch': './cordis.patch.yml'}},
                    'dependencies': {dependency: '1.0.0'},
                    'scripts': {'postinstall': 'node -e "require(\'node:fs\').writeFileSync(\'/workspace-native/' +
                                name + '/HOOK_MUST_NOT_RUN\',\'unexpected\')"'}}
        source = plugin_source(version, dependency, workspace+'/events.log', module_path)
        # A candidate's new entry can actually be evaluated even when a
        # same-path replacement must wait for the process to restart.
        entry = name+'/candidate' if version == '1.2.0' else name
        patch = json.dumps([{'insert': [{'id': name, 'name': entry}]}])
        built[version] = register_release(server, manifest, {
            'index.mjs': source, 'candidate.mjs': source, 'cordis.patch.yml': patch,
        })
    server.responses['/'+name] = json_body(registry_record(name, built, '1.1.0'))
    versions = [{'version': version, 'publishTimestamp': 1704067200, 'engines': built[version]['engines'],
                 'source': {'type': 'npm', 'registry': server.base+'/'}} for version in VERSIONS]
    server.responses['/market.json'] = json_body({'format': 1, 'title': 'Owned test market', 'plugins': [
        {'name': name, 'title': 'Harmony market fixture', 'versions': versions},
        {'name': dependency, 'title': 'Dependency metadata fixture', 'versions': versions[:1]},
    ]})
    server.responses['/invalid.json'] = json_body({'format': 2, 'title': 'Invalid fixture', 'plugins': []})


def rejection(emulator, method, args, code):
    try:
        emulator.rpc(method, args)
    except RuntimeError as error:
        assert str(error) == f'{method}: {code}', error
    else:
        raise AssertionError(f'{method} succeeded unexpectedly')


def catalog(emulator, name):
    rows = [row for row in emulator.rpc('pluginManager/listBundles', {}) if row['name'] == name]
    return rows[0] if rows else None


def market(emulator, enabled):
    row = catalog(emulator, BUNDLE)
    assert row and row['availability'] == 'installation' and row['optional'] and row['official'], row
    assert not row['removable'] and not row.get('error') and row['enabled'] == enabled, row
    return {key: row[key] for key in ['availability', 'enabled', 'optional', 'official', 'version']}


def switch(emulator, enabled):
    result = emulator.rpc('pluginManager/setBundleEnabled', {'name': BUNDLE, 'enabled': enabled})
    assert result['application'] in ['applied', 'restart-required'], result
    emulator.stop()
    emulator.start()
    return emulator.ready('normal')


def search(emulator, url, **options):
    query = {'sort': {'kind': 'index'}, 'offset': 0, 'limit': 1, **options}
    return emulator.rpc('pluginMarket/search', {'url': url, 'query': query})


def configure_indexes(emulator, server, evidence):
    index_url = server.base+'/market.json'
    invalid_url = server.base+'/invalid.json'
    assert not emulator.rpc('pluginMarket/listIndexes', {}), 'Expected independent test profile with no market source'
    rejection(emulator, 'pluginMarket/search', {'url': index_url, 'query': {
        'sort': {'kind': 'index'}, 'offset': 0, 'limit': 1,
    }}, 'plugin-market/unknown-index')
    assert '/market.json' not in server.requests
    emulator.rpc('pluginMarket/setIndexes', {'urls': [index_url, invalid_url]})
    rejection(emulator, 'pluginMarket/setIndexes', {'urls': [index_url, index_url]}, 'plugin-market/invalid-index-url')
    rejection(emulator, 'pluginMarket/search', {'url': invalid_url, 'query': {
        'sort': {'kind': 'index'}, 'offset': 0, 'limit': 1,
    }}, 'plugin-market/invalid-index')

    first = search(emulator, index_url)
    assert first['title'] == 'Owned test market' and first['total'] == 2 and first['nextOffset'] == 1, first
    second = search(emulator, index_url, offset=1, fetchedAt=first['fetchedAt'])
    assert second['total'] == 2 and second['nextOffset'] is None and first['fetchedAt'] == second['fetchedAt'], second
    assert second['entries'][0]['name'] == first['entries'][0]['name']+'-dep'
    assert server.requests.count('/market.json') == 1
    evidence['firstPage'] = first
    evidence['secondPage'] = second
    evidence['indexSummaries'] = emulator.rpc('pluginMarket/listIndexes', {})
    assert evidence['indexSummaries'][0]['title'] == first['title']
    assert evidence['indexSummaries'][1].get('error')
    print('Verified native index worker, index validation and cached pagination', flush=True)
    return first['entries'][0], index_url


def assert_tool(emulator, session, version):
    marker = 'MARKET_' + uuid.uuid4().hex.upper()
    result, _ = agent['tool'](emulator, session, 'mh_market_probe', {'marker': marker})
    value = json.loads(agent['toolkit']['texts']([result]))
    assert value == {'version': version, 'dependency': 'OWNED_DEPENDENCY_LOADED', 'marker': marker}, value
    return value


def installed(emulator, name, version):
    row = catalog(emulator, name)
    assert row and row['enabled'] and row['installed'] and row['version'] == version and row['update'] == 'registry', row


def snapshot(emulator, folder, installed_name):
    raw = emulator.app(f'cat {folder}/events.log')
    assert emulator.app(f'test ! -e {folder}/HOOK_MUST_NOT_RUN && test ! -e {PROFILE}/node_modules/{installed_name}/HOOK_MUST_NOT_RUN && printf ABSENT') == 'ABSENT'
    return raw.splitlines()


def origin_path(name):
    return PROFILE + '/.plugin-manager/registry-origins/' + hashlib.sha256(name.encode()).hexdigest() + '.json'


def activate_version(emulator, result, version, evidence):
    assert result['version'] == version and result['enabled'], result
    if result['application'] == 'applied':
        return
    assert result['application'] == 'restart-required' and result['restartReason'] == 'module-comparison', result
    emulator.stop()
    emulator.start()
    evidence[version] = {'reason': result['restartReason'], 'readyMs': emulator.ready('normal')}


def verify(emulator, server, name, folder, evidence):
    entry, index_url = configure_indexes(emulator, server, evidence)
    assert entry['name'] == name and entry['installation']['status'] == 'not-installed', entry
    versions = {row['version']: row for row in entry['versions']}
    assert set(versions) == set(VERSIONS) and not versions['2.0.0']['compatibility']['compatible'], versions
    target = versions['1.0.0']['install']
    assert target == {'spec': name+'@1.0.0', 'registry': server.base+'/'}, target
    result = emulator.rpc('pluginManager/installBundle', {'spec': target['spec'], 'options': {
        'registry': target['registry'], 'enabled': True, 'saveExact': True,
    }}, timeout=100)
    evidence['firstInstall'] = result
    assert result['application'] == 'applied' and result['version'] == '1.0.0', result
    installed(emulator, name, '1.0.0')
    evidence['marketAfterInstall'] = search(emulator, index_url, text='Harmony fixtures')['entries'][0]['installation']
    assert evidence['marketAfterInstall']['installedVersion'] == '1.0.0'
    listing = emulator.rpc('pluginManager/listVersions', {'name': name, 'options': {'registry': target['registry']}}, timeout=85)
    evidence['registryVersionListing'] = listing
    assert listing['status'] == 'listed' and listing['installed'] == '1.0.0', listing
    assert [item['version'] for item in listing['versions']] == ['2.0.0','1.2.0','1.1.0'], listing
    assert listing['versions'][0]['incompatible'], listing

    def update(version, explicit_registry=True):
        options = {'requestId': str(uuid.uuid4())}
        if explicit_registry:
            options['registry'] = target['registry']
        value = emulator.rpc('pluginManager/updateBundle', {'name': name, 'version': version,
            'options': options}, timeout=125)
        evidence.setdefault('updates', {})[version] = value
        return value

    with support['model_key'](emulator):
        session = support['session'](emulator, True)
        evidence['sessionId'] = session
        evidence['firstPluginToolResult'] = assert_tool(emulator, session, '1.0.0')
        print('Verified real installed tool and dependency', flush=True)
        before = snapshot(emulator, folder, name)
        refused = update('2.0.0')
        assert refused['step'] == 'check' and refused['result']['error']['code'] == 'incompatible-version', refused
        assert snapshot(emulator, folder, name) == before
        installed(emulator, name, '1.0.0')
        accepted = update('1.1.0')
        assert accepted['step'] == 'install' and 'restore' not in accepted, accepted
        evidence['activationRestarts'] = {}
        activate_version(emulator, accepted['result'], '1.1.0', evidence['activationRestarts'])
        installed(emulator, name, '1.1.0')
        origin = json.loads(agent['read_bytes'](emulator, origin_path(name)))
        assert origin == {'name': name, 'version': '1.1.0', 'registry': target['registry']}, origin
        evidence['registryOriginAfterRestart'] = origin
        evidence['updatedToolResult'] = assert_tool(emulator, session, '1.1.0')
        print('Verified the upgraded tool after honoring restart-required', flush=True)
        rollback = update('1.2.0', explicit_registry=False)
        assert rollback['result']['application'] == 'failed' and rollback['result']['stage'] == 'enable', rollback
        candidate = snapshot(emulator, folder, name)
        assert candidate.count('start 1.2.0') == 1
        evidence['rollbackRestarts'] = {}
        activate_version(emulator, rollback['restore'], '1.1.0', evidence['rollbackRestarts'])
        installed(emulator, name, '1.1.0')
        evidence['toolAfterRollback'] = assert_tool(emulator, session, '1.1.0')
    evidence['testCredentialRemoved'] = True
    evidence['realLifecycle'] = snapshot(emulator, folder, name)
    starts = [event for event in evidence['realLifecycle'] if event.startswith('start ')]
    transitions = [event for event, _ in groupby(starts)]
    assert transitions == ['start 1.0.0', 'start 1.1.0', 'start 1.2.0', 'start 1.1.0'], starts
    assert starts.count('start 1.2.0') == 1, starts
    evidence['lifecycleScriptWasSuppressed'] = True
    removed = emulator.rpc('pluginManager/removeBundle', {'name': name}, timeout=100)
    assert removed['application'] in ['applied', 'restart-required'] and removed['packageResult']['exitCode'] == 0, removed
    assert catalog(emulator, name) is None
    assert emulator.app(f'test ! -e {origin_path(name)} && printf ABSENT') == 'ABSENT'
    if removed['application'] == 'restart-required':
        assert removed['restartReason'] == 'module-comparison', removed
        emulator.stop()
        emulator.start()
        evidence['removedReadyMs'] = emulator.ready('normal')
    assert catalog(emulator, name) is None
    evidence['removedViaManager'] = True
    print('Verified registry install, dependency loading, upgrade and activation rollback', flush=True)


def run(emulator, output):
    name = 'mh-market-' + uuid.uuid4().hex[:10]
    folder = 'alpine/workspace-native/' + name
    root = support['WORKSPACE'].rsplit('/', 1)[0]
    workspace = support['WORKSPACE'] + '/' + name
    remote = '/data/local/tmp/' + name
    originals = {}
    evidence = {'fixture': name}
    server = ThreadingHTTPServer(('127.0.0.1', 0), Registry)
    server.base = f'http://127.0.0.1:{DEVICE_PORT}'
    server.requests = []
    server.responses = {}
    populate(server, name, root, workspace)
    reverse = (f'tcp:{DEVICE_PORT}', f'tcp:{server.server_port}')
    task = threading.Thread(target=server.serve_forever, daemon=True)
    task.start()
    forwarded = False
    try:
        emulator.ready('normal')
        for path in [PROFILE+'/package.json', PROFILE+'/pnpm-lock.yaml', 'mobile-harness-boot.json',
                     PROFILE+'/cordis.patch.yml']:
            exists = emulator.app(f'test -f {path} && printf PRESENT') == 'PRESENT'
            originals[path] = agent['read_bytes'](emulator, path) if exists else None
        evidence['defaultCatalog'] = market(emulator, False)
        emulator.app('mkdir ' + folder)
        reply = emulator.hdc('rport', *reverse)
        assert 'Forwardport result:OK' in reply, reply
        forwarded = True
        evidence['enabledReadyMs'] = switch(emulator, True)
        evidence['enabledCatalog'] = market(emulator, True)
        verify(emulator, server, name, folder, evidence)
        emulator.rpc('pluginMarket/setIndexes', {'urls': []})
        evidence['disabledReadyMs'] = switch(emulator, False)
        evidence['disabledCatalog'] = market(emulator, False)
    finally:
        try:
            if originals:
                # Keep recovery independent of any failure in the package manager.
                emulator.stop()
                emulator.app(f'rm -rf {folder} {PROFILE}/node_modules/{name} {PROFILE}/node_modules/{name}-dep')
                emulator.app('rm -f ' + origin_path(name))
                for i, (path, body) in enumerate(originals.items()):
                    if body is None:
                        emulator.app('rm -f ' + path)
                    else:
                        lsp['restore_bytes'](emulator, path, body, remote+'-'+str(i))
                emulator.start()
                evidence['restoredReadyMs'] = emulator.ready('normal')
                for path, body in originals.items():
                    if body is None:
                        assert emulator.app(f'test ! -e {path} && printf ABSENT') == 'ABSENT'
                    else:
                        assert agent['read_bytes'](emulator, path) == body
                evidence['restoredConfigurationHashes'] = {
                    path: hashlib.sha256(body).hexdigest() if body is not None else None for path, body in originals.items()
                }
        finally:
            if forwarded:
                emulator.hdc('fport', 'rm', *reverse)
                assert ' '.join(reverse) not in emulator.hdc('fport', 'ls')
            server.shutdown()
            server.server_close()
            evidence['fixtureRequestPaths'] = server.requests
            output.write_text(json.dumps(evidence, indent=2, ensure_ascii=False)+'\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('target')
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    if not os.environ.get('MH_TEST_DEEPSEEK_API_KEY'):
        parser.error('MH_TEST_DEEPSEEK_API_KEY is required')
    emulator = support['Emulator'](args.target, 19643)
    forward = ('tcp:19643', 'tcp:19592')
    emulator.hdc('fport', *forward)
    try:
        run(emulator, args.output)
    finally:
        emulator.hdc('fport', 'rm', *forward)
