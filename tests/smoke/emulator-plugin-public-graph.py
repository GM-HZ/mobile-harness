"""Load a real public npm dependency graph through the HarmonyOS PluginManager."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import runpy
import uuid

market = runpy.run_path(str(Path(__file__).with_name('emulator-plugin-market.py')))
agent, support, lsp = (market[key] for key in ('agent', 'support', 'lsp'))
PROFILE = market['PROFILE']
REGISTRY = 'https://registry.npmjs.org/'
DEPENDENCIES = {'string-width': '7.2.0', 'number-is-nan': '1.0.1', 'is-odd': '3.0.1'}
NATIVE_NAME = '@node-rs/crc32-linux-arm64-musl'
NATIVE_VERSION = '1.10.6'
NATIVE_INTEGRITY = 'sha512-k8ra/bmg0hwRrIEE8JL1p32WfaN9gDlUUpQRWsbxd1WhjqvXea7kKO6K4DwVxyxlPhBS9Gkb5Urq7Y4mXANzaw=='
INTEGRITIES = {
    'string-width': 'sha512-tsaTIkKW9b4N+AEj+SVA+WhJzV7/zMhcSu78mLKWSk7cXMOSHsBKFWUs0fWwq8QyK3MgJBQRX6Gbi4kYbdvGkQ==',
    'number-is-nan': 'sha512-4jbtZXNAsfZbAHiiqjLPBiCl16dES1zI4Hpzzxw61Tk+loF+sBDBKx1ICKKKwIqQ7M0mFn1TmkN7euSncWgHiQ==',
}


WRAPPERS = {'@node-rs/crc32': '1.10.6', '@parcel/watcher': '2.5.1'}
WRAPPER_INTEGRITIES = {
    '@node-rs/crc32': 'sha512-+llXfqt+UzgoDzT9of5vPQPGqTAVCohU74I9zIBkNo5TH6s2P31DFJOGsJQKN207f0GHnYv5pV3wh3BCY/un/A==',
    NATIVE_NAME: NATIVE_INTEGRITY,
    '@parcel/watcher': 'sha512-dfUnCxiN9H4ap84DvD2ubjw+3vUNpstxa0TneY/Paat8a3R4uQZDLSvWjmznAY/DoahqTHl9V46HF/Zs3F29pg==',
    '@parcel/watcher-linux-arm64-musl': 'sha512-cFOjABi92pMYRXS7AcQv9/M1YuKRw8SZniCDw0ssQb/noPkRzA+HBDkwmyOJYp5wXcsTrhxO0zq1U11cK9jsFg==',
}
NATIVE_WRAPPER_PROBE = """
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const { crc32 } = require(process.argv[1]);
const watcher = require(process.argv[2]);
const shim = process.argv[3];
const info = fs.lstatSync(shim);
if (!info.isFile() || !(info.mode & 0o100)) throw new Error('Expected a regular executable command shim');
const env = { ...process.env };
delete env.LIBC;
const libc = spawnSync('/bin/sh', [shim, '/bin/busybox', 'printenv', 'LIBC'], {
  encoding: 'utf8', timeout: 5000, env,
});
if (libc.status !== 0) throw new Error('Dependency command shim could not run: ' + libc.stderr);
const target = path.join(process.cwd(), 'watch-fixture.txt');
(async () => {
  let resolveEvent, rejectEvent;
  const event = new Promise((resolve, reject) => { resolveEvent = resolve; rejectEvent = reject; });
  const subscription = await watcher.subscribe(process.cwd(), (error, events) => {
    if (error) return rejectEvent(error);
    const created = events.find(item => path.basename(item.path) === 'watch-fixture.txt' && item.type === 'create');
    if (created) resolveEvent(created.type);
  }, { backend: 'inotify' });
  const timer = setTimeout(() => rejectEvent(new Error('No filesystem change from the native watcher')), 6000);
  try {
    fs.writeFileSync(target, 'harmless workspace fixture', { flag: 'wx' });
    const eventType = await event;
    const binaries = Object.keys(require.cache).filter(name => name.endsWith('.node')).sort();
    console.log(JSON.stringify({
      platform: process.platform, arch: process.arch, crc32: crc32(Buffer.from('123456789')),
      event: eventType, bindings: binaries.map(name => name.split('/node_modules/').at(-1)),
      shimLibc: libc.stdout.trim(),
    }));
  } finally {
    clearTimeout(timer);
    await subscription.unsubscribe();
    fs.rmSync(target, { force: true });
  }
})().catch(error => { console.error(error.message); process.exitCode = 1; });
"""


def plugin_files(name, workspace, native_mode):
    manifest = {
        'name': name,
        'version': '1.0.0',
        'type': 'module',
        'exports': './index.mjs',
        'dsh': {'bundle': {'patch': './cordis.patch.yml'}},
        'dependencies': {name: DEPENDENCIES[name] for name in ('string-width', 'number-is-nan')},
        'peerDependencies': {'@deepseek-ai/dsh-tools': '0.2.2-rc.5'},
        'optionalDependencies': {'is-odd': DEPENDENCIES['is-odd']},
    }
    if native_mode == 'direct':
        manifest['dependencies'][NATIVE_NAME] = NATIVE_VERSION
    elif native_mode == 'wrapper':
        manifest['dependencies'].update(WRAPPERS)
    probe = NATIVE_WRAPPER_PROBE if native_mode == 'wrapper' else 'console.log(require(process.argv[1]).crc32(Buffer.from("123456789")))'
    dependencies = list(WRAPPERS) if native_mode == 'wrapper' else [NATIVE_NAME]
    patch = [{'insert': [{'id': name, 'name': name}]}]
    source = f'''
import {{ defineTool }} from '@deepseek-ai/dsh-tools';
import stringWidth from 'string-width';
import isNaN from 'number-is-nan';
import isOdd from 'is-odd';
import {{ createRequire }} from 'node:module';
import {{ join }} from 'node:path';
const native = {json.dumps(native_mode)};
const workspace = {json.dumps(workspace)};
export const inject = native ? ['tools', 'subprocess'] : ['tools'];
export function apply(ctx) {{
  ctx.tools.register(defineTool({{
    name: 'mh_public_npm_graph',
    description: 'Run the public npm dependency acceptance probe.',
    parameters: {{ value: {{ type: 'string', required: true }} }},
    output: {{
      schema: {{ type: 'object', additionalProperties: true, properties: {{}} }},
      render(_args, value) {{ return [{{ type: 'text', text: JSON.stringify(value) }}]; }},
    }},
    async execute({{ value }}, exec) {{
      let nativeResult;
      if (native) {{
        const require = createRequire(import.meta.url);
        const installed = {json.dumps(dependencies)}.map(name => require.resolve(name));
        if (native === 'wrapper') installed.push(join(import.meta.dirname, '../.bin/detect-libc'));
        const node = await ctx.subprocess.resolveExecutable('node', undefined, exec.signal);
        const child = ctx.subprocess.spawn({{
          argv: [node, '-e', {json.dumps(probe)}, ...installed],
          cwd: workspace,
          signal: exec.signal,
          graceMs: 1000,
          stdio: {{ stdin: 'ignore', stdout: {{ maxBytes: 8192 }}, stderr: {{ maxBytes: 8192 }} }},
        }});
        try {{
          const outcome = await child.done;
          if (outcome.exitCode !== 0) throw new Error(child.collected.stderr.readFrom(0).text);
          const raw = child.collected.stdout.readFrom(0).text;
          nativeResult = native === 'wrapper' ? JSON.parse(raw) : Number(raw);
        }} finally {{
          child.terminate();
          await child.waitForExit();
        }}
      }}
      return {{
        width: stringWidth(value),
        commonJsNaN: isNaN(Number.NaN),
        commonJsString: isNaN('NaN'),
        dshToolsPeer: import.meta.resolve('@deepseek-ai/dsh-tools'),
        optionalOdd: isOdd(5),
        ...native === 'wrapper' ? {{ native: nativeResult }} : {{ nativeCrc32: nativeResult }},
      }};
    }},
  }}));
}}
'''
    return {'package.json': json.dumps(manifest), 'cordis.patch.yml': json.dumps(patch), 'index.mjs': source}


def verify_lock(device, original, native_mode):
    lock = agent['read_bytes'](device, PROFILE + '/pnpm-lock.yaml').decode()
    baseline = (original or b'').decode()
    added = {line.strip() for line in lock.splitlines()} - {line.strip() for line in baseline.splitlines()}
    packages = [f'{name}@{version}' for name, version in DEPENDENCIES.items()]
    integrities = dict(INTEGRITIES)
    if native_mode == 'direct':
        packages.append(f'{NATIVE_NAME}@{NATIVE_VERSION}')
        integrities[NATIVE_NAME] = NATIVE_INTEGRITY
    elif native_mode == 'wrapper':
        packages.extend(f'{name}@{version}' for name, version in
                        {**WRAPPERS, NATIVE_NAME: NATIVE_VERSION, '@parcel/watcher-linux-arm64-musl': '2.5.1'}.items())
        integrities.update(WRAPPER_INTEGRITIES)
    entries = {line[:-1].strip("'\"") for line in added if line.endswith(':')}
    for package in packages:
        assert package in entries, package
    for name in ('ansi-regex', 'emoji-regex', 'get-east-asian-width', 'is-number', 'strip-ansi'):
        assert any(line.startswith(name + '@') and line.endswith(':') for line in added), name
    for integrity in integrities.values():
        assert integrity in lock and integrity not in baseline, integrity
    assert not any('dsh-tools@' in line for line in added if line.endswith(':'))
    assert 'autoInstallPeers: false' in lock
    return {'directAndOptional': packages, 'integrity': integrities, 'singleBundledHostPeer': True,
            'newPackageEntries': sorted(line[:-1] for line in added if '@' in line and line.endswith(':'))}


def run(device, output, host_port, native_mode=None):
    name = 'mh-public-npm-' + uuid.uuid4().hex[:10]
    folder = 'alpine/workspace-native/' + name
    path = support['WORKSPACE'] + '/' + name
    remote = '/data/local/tmp/' + name
    evidence = {'registry': REGISTRY}
    originals = {}
    workspace = None
    session = None
    bridge = (f'tcp:{host_port}', 'tcp:19592')
    assert 'Forwardport result:OK' in device.hdc('fport', *bridge)
    try:
        device.ready('normal')
        paths = [PROFILE + '/' + leaf for leaf in ('package.json', 'pnpm-lock.yaml', 'cordis.patch.yml')]
        originals = {entry: market['profile_file'](device, entry) for entry in paths + ['mobile-harness-boot.json']}
        device.app('mkdir ' + folder)
        for leaf, data in plugin_files(name, path, native_mode).items():
            lsp['restore_bytes'](device, f'{folder}/{leaf}', data.encode(), f'{remote}-{leaf}')
        result = device.rpc('pluginManager/installBundle', {
            'spec': 'file:' + path,
            'options': {'enabled': True, 'registry': REGISTRY, 'saveExact': True},
        }, timeout=150)
        evidence['installation'] = result
        assert result['application'] in ('applied', 'restart-required'), result
        assert result['enabled'] and result['version'] == '1.0.0', result
        evidence['lock'] = verify_lock(device, originals[paths[1]], native_mode)
        device.stop()
        device.start()
        evidence['restartReadyMs'] = device.ready('normal')
        bundle = market['catalog'](device, name)
        assert bundle['installed'] and bundle['enabled'] and bundle['version'] == '1.0.0', bundle
        workspace = device.rpc('workspace/create', {'request': {'path': path}})['workspace']['workspaceId']
        with support['model_key'](device):
            session = device.rpc('session/create', {'request': {'workspaceId': workspace}})['sessionId']
            device.rpc('session/selectModel', {'request': {'sessionId': session, 'provider': 'deepseek-official',
                       'model': 'deepseek-flash', 'reasoningEffort': 'off'}})
            reply, _ = agent['tool'](device, session, 'mh_public_npm_graph',
                                      {'value': '\x1b[32m手机😀\x1b[0mA'}, literal_unicode=True)
            value = json.loads(agent['toolkit']['texts']([reply]))
        peer = value.pop('dshToolsPeer')
        assert peer.endswith('/.dsh-0.2.2-rc.5/dsh/node_modules/@deepseek-ai/dsh-tools/lib/index.js'), peer
        expected = {'width': 7, 'commonJsNaN': True, 'commonJsString': False, 'optionalOdd': True}
        if native_mode == 'direct':
            expected['nativeCrc32'] = 0xcbf43926
        elif native_mode == 'wrapper':
            expected['native'] = {'platform': 'linux', 'arch': 'arm64', 'crc32': 0xcbf43926,
                                  'event': 'create', 'shimLibc': 'musl', 'bindings': [
                '@node-rs/crc32-linux-arm64-musl/crc32.linux-arm64-musl.node',
                '@parcel/watcher-linux-arm64-musl/watcher.node',
            ]}
        assert value == expected, value
        evidence['actualTool'] = value
        evidence['bundledDshToolsPeer'] = peer
        removed = device.rpc('pluginManager/removeBundle', {'name': name}, timeout=125)
        evidence['removal'] = removed
        assert removed['application'] in ('applied', 'restart-required'), removed
        assert market['catalog'](device, name) is None
    finally:
        try:
            if session:
                device.rpc('workspace/archiveSession', {'request': {'sessionId': session}})
            if workspace:
                assert device.rpc('workspace/delete', {'request': {'workspaceId': workspace}}) == {'deleted': True}
        finally:
            try:
                if originals:
                    device.stop()
                    device.app(f'rm -rf {folder} {PROFILE}/node_modules/{name}')
                    for i, (entry, data) in enumerate(originals.items()):
                        if data is None:
                            device.app('rm -f ' + entry)
                        else:
                            lsp['restore_bytes'](device, entry, data, remote + str(i))
                    device.start()
                    evidence['restoredReadyMs'] = device.ready('normal')
                    assert all(market['profile_file'](device, entry) == data for entry, data in originals.items())
                    assert market['catalog'](device, name) is None
                    evidence['restoredHashes'] = {
                        entry: hashlib.sha256(data).hexdigest() if data is not None else None for entry, data in originals.items()
                    }
            finally:
                device.hdc('fport', 'rm', *bridge)
                output.write_text(json.dumps(evidence, indent=2, ensure_ascii=False) + '\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('target')
    parser.add_argument('output', type=Path)
    parser.add_argument('--host-port', type=int, default=19643)
    native = parser.add_mutually_exclusive_group()
    native.add_argument('--native', dest='native_mode', action='store_const', const='direct',
                        help='Load a fixed ARM64 musl Node addon in a managed subprocess')
    native.add_argument('--native-wrapper', dest='native_mode', action='store_const', const='wrapper',
                        help='Load two public Node packages through their standard platform selectors')
    args = parser.parse_args()
    if not os.environ.get('MH_TEST_DEEPSEEK_API_KEY'):
        parser.error('MH_TEST_DEEPSEEK_API_KEY is required')
    run(support['Emulator'](args.target, args.host_port), args.output, args.host_port, args.native_mode)
