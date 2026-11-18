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


def plugin_files(name, workspace, native):
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
    if native:
        manifest['dependencies'][NATIVE_NAME] = NATIVE_VERSION
    patch = [{'insert': [{'id': name, 'name': name}]}]
    source = f'''
import {{ defineTool }} from '@deepseek-ai/dsh-tools';
import stringWidth from 'string-width';
import isNaN from 'number-is-nan';
import isOdd from 'is-odd';
import {{ createRequire }} from 'node:module';
const native = {json.dumps(native)};
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
      let nativeCrc32;
      if (native) {{
        const require = createRequire(import.meta.url);
        const installed = require.resolve({json.dumps(NATIVE_NAME)});
        const node = await ctx.subprocess.resolveExecutable('node', undefined, exec.signal);
        const child = ctx.subprocess.spawn({{
          argv: [node, '-e', 'console.log(require(process.argv[1]).crc32(Buffer.from("123456789")))', installed],
          cwd: workspace,
          signal: exec.signal,
          graceMs: 1000,
          stdio: {{ stdin: 'ignore', stdout: {{ maxBytes: 8192 }}, stderr: {{ maxBytes: 8192 }} }},
        }});
        try {{
          const outcome = await child.done;
          if (outcome.exitCode !== 0) throw new Error(child.collected.stderr.readFrom(0).text);
          nativeCrc32 = Number(child.collected.stdout.readFrom(0).text);
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
        nativeCrc32,
      }};
    }},
  }}));
}}
'''
    return {'package.json': json.dumps(manifest), 'cordis.patch.yml': json.dumps(patch), 'index.mjs': source}


def verify_lock(device, original, native):
    lock = agent['read_bytes'](device, PROFILE + '/pnpm-lock.yaml').decode()
    added = {line.strip() for line in lock.splitlines()} - {line.strip() for line in original.decode().splitlines()}
    packages = [f'{name}@{version}' for name, version in DEPENDENCIES.items()]
    integrities = dict(INTEGRITIES)
    if native:
        packages.append(f'{NATIVE_NAME}@{NATIVE_VERSION}')
        integrities[NATIVE_NAME] = NATIVE_INTEGRITY
    entries = {line[:-1].strip("'\"") for line in added if line.endswith(':')}
    for package in packages:
        assert package in entries, package
    for name in ('ansi-regex', 'emoji-regex', 'get-east-asian-width', 'is-number', 'strip-ansi'):
        assert any(line.startswith(name + '@') and line.endswith(':') for line in added), name
    for integrity in integrities.values():
        assert integrity in lock and integrity not in original.decode(), integrity
    assert not any('dsh-tools@' in line for line in added if line.endswith(':'))
    assert 'autoInstallPeers: false' in lock
    return {'directAndOptional': packages, 'integrity': integrities, 'singleBundledHostPeer': True,
            'newPackageEntries': sorted(line[:-1] for line in added if '@' in line and line.endswith(':'))}


def run(device, output, native=False):
    name = 'mh-public-npm-' + uuid.uuid4().hex[:10]
    folder = 'alpine/workspace-native/' + name
    path = support['WORKSPACE'] + '/' + name
    remote = '/data/local/tmp/' + name
    evidence = {'registry': REGISTRY}
    originals = {}
    workspace = None
    session = None
    bridge = ('tcp:19643', 'tcp:19592')
    assert 'Forwardport result:OK' in device.hdc('fport', *bridge)
    try:
        device.ready('normal')
        paths = [PROFILE + '/' + leaf for leaf in ('package.json', 'pnpm-lock.yaml', 'cordis.patch.yml')]
        originals = {entry: agent['read_bytes'](device, entry) for entry in paths + ['mobile-harness-boot.json']}
        device.app('mkdir ' + folder)
        for leaf, data in plugin_files(name, path, native).items():
            lsp['restore_bytes'](device, f'{folder}/{leaf}', data.encode(), f'{remote}-{leaf}')
        result = device.rpc('pluginManager/installBundle', {
            'spec': 'file:' + path,
            'options': {'enabled': True, 'registry': REGISTRY, 'saveExact': True},
        }, timeout=150)
        evidence['installation'] = result
        assert result['enabled'] and result['version'] == '1.0.0', result
        assert result['application'] in ('applied', 'restart-required'), result
        evidence['lock'] = verify_lock(device, originals[paths[1]], native)
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
            reply, _ = agent['tool'](device, session, 'mh_public_npm_graph', {'value': '\x1b[32m手机😀\x1b[0mA'})
            value = json.loads(agent['toolkit']['texts']([reply]))
        peer = value.pop('dshToolsPeer')
        assert peer.endswith('/.dsh-0.2.2-rc.5/dsh/node_modules/@deepseek-ai/dsh-tools/lib/index.js'), peer
        expected = {'width': 7, 'commonJsNaN': True, 'commonJsString': False, 'optionalOdd': True}
        if native:
            expected['nativeCrc32'] = 0xcbf43926
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
                        lsp['restore_bytes'](device, entry, data, remote + str(i))
                    device.start()
                    evidence['restoredReadyMs'] = device.ready('normal')
                    assert all(agent['read_bytes'](device, entry) == data for entry, data in originals.items())
                    assert market['catalog'](device, name) is None
                    evidence['restoredHashes'] = {
                        entry: hashlib.sha256(data).hexdigest() for entry, data in originals.items()
                    }
            finally:
                device.hdc('fport', 'rm', *bridge)
                output.write_text(json.dumps(evidence, indent=2, ensure_ascii=False) + '\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('target')
    parser.add_argument('output', type=Path)
    parser.add_argument('--native', action='store_true', help='Also load a public ARM64 musl Node add-on in a managed subprocess')
    args = parser.parse_args()
    if not os.environ.get('MH_TEST_DEEPSEEK_API_KEY'):
        parser.error('MH_TEST_DEEPSEEK_API_KEY is required')
    run(support['Emulator'](args.target, 19643), args.output, args.native)
