"""Validate the real public Harmony subprocess provider using a temporary standard bundle."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import runpy
import tarfile
import tempfile
import uuid

agent = runpy.run_path(str(Path(__file__).with_name('emulator-agent-continuation.py')))
support = agent['support']; toolkit = agent['toolkit']
worktree = runpy.run_path(str(Path(__file__).with_name('emulator-worktree.py')))
PROFILE = 'alpine/native-benchmark-home/profiles/web'


def archive_fixture(destination, name):
    root = support['WORKSPACE'].rsplit('/', 1)[0]
    source = Path(__file__).with_name('fixtures').joinpath('subprocess-provider.mjs').read_text()
    source = source.replace('__MH_DSH_PACKAGES__', json.dumps('file://' + root + '/.dsh-0.2.2-rc.4/dsh/node_modules/@deepseek-ai/'))
    source = source.replace('__MH_ROOT__', json.dumps(root)).replace('__MH_WORKSPACE__', json.dumps(support['WORKSPACE'] + '/' + name))
    files = {
        'package.json': json.dumps({'name': name, 'version': '1.0.0', 'type': 'module', 'main': 'index.js',
             'scripts': {'postinstall': 'node -e "require(\'node:fs\').writeFileSync(\'/workspace-native/' + name + '/INSTALL_SCRIPT_SHOULD_NOT_RUN\',\'bad\')"'},
             'files': ['index.js', 'cordis.patch.yml'], 'dsh': {'bundle': {'patch': './cordis.patch.yml'}}}).encode(),
        'cordis.patch.yml': f'- insert:\n    - id: {name}\n      name: {name}\n'.encode(),
        'index.js': source.encode(),
    }
    with tarfile.open(destination, 'w:gz', format=tarfile.USTAR_FORMAT) as archive:
        for filename, data in files.items():
            entry = tarfile.TarInfo(filename); entry.size = len(data); archive.addfile(entry, io.BytesIO(data))


def run(emulator, output):
    name = 'mh-subprocess-' + uuid.uuid4().hex[:10]
    remote = '/data/local/tmp/' + name
    backup = f'{PROFILE}/package.json.{name}'; lock_backup = f'{PROFILE}/pnpm-lock.yaml.{name}'
    boot_backup = 'mobile-harness-boot.json.' + name
    evidence = {'fixture': name}; saved = False; had_lock = False; sid = None
    try:
        emulator.ready('normal')
        assert emulator.app('test ! -e alpine/native-benchmark-home/cordis.patch.yml && printf EMPTY') == 'EMPTY'
        assert emulator.app(f'cp {PROFILE}/package.json {backup} && cp mobile-harness-boot.json {boot_backup} && printf SAVED') == 'SAVED'
        saved = True
        evidence['manifestBeforeSha256'] = hashlib.sha256(agent['read_bytes'](emulator, PROFILE + '/package.json')).hexdigest()
        had_lock = emulator.app(f'test -e {PROFILE}/pnpm-lock.yaml && printf PRESENT') == 'PRESENT'
        if had_lock: emulator.app(f'cp {PROFILE}/pnpm-lock.yaml {lock_backup}')
        evidence['lockBeforeSha256'] = hashlib.sha256(agent['read_bytes'](emulator, PROFILE + '/pnpm-lock.yaml')).hexdigest() if had_lock else None
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary); archive = folder / 'fixture.tgz'; archive_fixture(archive, name)
            assert 'FileTransfer finish' in emulator.hdc('file', 'send', str(archive), remote + '.tgz')
            assert emulator.app(f'mkdir alpine/workspace-native/{name} && tar -xzf {remote}.tgz -C alpine/workspace-native/{name} && printf READY') == 'READY'
            installed = emulator.rpc('pluginManager/installBundle', {'spec': f'file:{support["WORKSPACE"]}/{name}', 'options': {'enabled': False}}, timeout=90)
            assert installed.get('enabled') is False and installed['application'] != 'failed', installed
            assert emulator.app(f'test ! -e alpine/workspace-native/{name}/INSTALL_SCRIPT_SHOULD_NOT_RUN && printf ABSENT') == 'ABSENT'
            evidence['postinstallDidNotRun'] = True
            evidence['enable'] = emulator.rpc('pluginManager/setBundleEnabled', {'name': name, 'enabled': True})
            assert evidence['enable']['application'] != 'failed', evidence['enable']
            emulator.stop()
        emulator.start(); evidence['readyMs'] = emulator.ready('normal')
        with support['model_key'](emulator):
            sid = support['session'](emulator, True)
            evidence['sessionId'] = sid
            result, _ = agent['tool'](emulator, sid, 'mh_subprocess_contract', {})
            evidence['contract'] = json.loads(toolkit['texts']([result]))
            assert len(evidence['contract']) == 7, evidence['contract']
            evidence['allHelpersReaped'] = worktree['helpers_reaped'](emulator)
        evidence['temporaryModelCredentialRemoved'] = True
        evidence['disable'] = emulator.rpc('pluginManager/setBundleEnabled', {'name': name, 'enabled': False})
        assert evidence['disable']['application'] != 'failed', evidence['disable']
        emulator.stop(); emulator.start(); emulator.ready('normal')
        evidence['remove'] = emulator.rpc('pluginManager/removeBundle', {'name': name}, timeout=90)
        assert evidence['remove']['application'] != 'failed' and evidence['remove']['packageResult']['exitCode'] == 0, evidence['remove']
        manifest = json.loads(emulator.app(f'cat {PROFILE}/package.json'))
        assert name not in manifest['dependencies'] and name not in manifest['dsh']['profile']['bundles']
        assert emulator.app(f'test ! -e {PROFILE}/node_modules/{name} && printf ABSENT') == 'ABSENT'
        evidence['removedThroughActualPluginManager'] = True
    finally:
        try:
            if sid: emulator.rpc('session/cancel', {'request': {'sessionId': sid}})
            if saved:
                emulator.stop(); emulator.app(f'cp {backup} {PROFILE}/package.json && cp {boot_backup} mobile-harness-boot.json')
                if had_lock: emulator.app(f'cp {lock_backup} {PROFILE}/pnpm-lock.yaml')
                else: emulator.app(f'rm -f {PROFILE}/pnpm-lock.yaml')
                emulator.app(f'rm -f {backup} {lock_backup} {boot_backup}; rm -rf alpine/workspace-native/{name} {PROFILE}/node_modules/{name}')
                emulator.start(); emulator.ready('normal')
                evidence['manifestAfterSha256'] = hashlib.sha256(agent['read_bytes'](emulator, PROFILE + '/package.json')).hexdigest()
                evidence['lockAfterSha256'] = hashlib.sha256(agent['read_bytes'](emulator, PROFILE + '/pnpm-lock.yaml')).hexdigest() if had_lock else None
                assert evidence['manifestBeforeSha256'] == evidence['manifestAfterSha256']
                assert evidence['lockBeforeSha256'] == evidence['lockAfterSha256']
        finally:
            emulator.hdc('shell', 'rm', '-f', remote + '.tgz', remote + '.json')
            output.write_text(json.dumps(evidence, indent=2) + '\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('target'); parser.add_argument('output', type=Path); options = parser.parse_args()
    if not os.environ.get('MH_TEST_DEEPSEEK_API_KEY'): parser.error('MH_TEST_DEEPSEEK_API_KEY is required')
    emulator = support['Emulator'](options.target, 19643); forward = ('tcp:19643', 'tcp:19592')
    emulator.hdc('fport', *forward)
    try: run(emulator, options.output)
    finally: emulator.hdc('fport', 'rm', *forward)
