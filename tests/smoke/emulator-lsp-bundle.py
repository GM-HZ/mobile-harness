"""Built-in LSP ownership, disable persistence, and enablement through PluginManager."""
import argparse
import hashlib
import json
from pathlib import Path
import runpy
import uuid

agent = runpy.run_path(str(Path(__file__).with_name('emulator-agent-continuation.py')))
support = agent['support']
PROFILE = 'alpine/native-benchmark-home/profiles/web'
NAME = '@mobile-harness/lsp'


def bundle(emulator):
    found = [item for item in emulator.rpc('pluginManager/listBundles', {}) if item['name'] == NAME]
    assert len(found) == 1, found
    item = found[0]
    assert item['availability'] == 'installation' and not item['removable'] and not item.get('error'), item
    return {key: item[key] for key in ['name', 'availability', 'removable', 'enabled', 'version']}


def run(emulator, output):
    evidence = {}; suffix = '.mh-lsp-toggle-' + uuid.uuid4().hex[:8]
    saved = []; before = {}
    try:
        emulator.ready('normal')
        for path in [PROFILE + '/package.json', PROFILE + '/pnpm-lock.yaml', 'mobile-harness-boot.json']:
            exists = emulator.app('test -e ' + path + ' && printf PRESENT') == 'PRESENT'
            if exists:
                before[path] = hashlib.sha256(agent['read_bytes'](emulator, path)).hexdigest()
                assert emulator.app('cp ' + path + ' ' + path + suffix + ' && printf SAVED') == 'SAVED'
                saved.append(path)
        evidence['before'] = bundle(emulator); assert evidence['before']['enabled']
        evidence['disable'] = emulator.rpc('pluginManager/setBundleEnabled', {'name': NAME, 'enabled': False})
        assert evidence['disable']['application'] in ['applied', 'restart-required'], evidence['disable']
        emulator.stop(); emulator.start(); evidence['disabledRestartReadyMs'] = emulator.ready('normal')
        evidence['afterDisabledRestart'] = bundle(emulator); assert not evidence['afterDisabledRestart']['enabled']
        active = [row for row in emulator.rpc('pluginManager/listPlugins', {})
                  if row['moduleName'] in ['@deepseek-ai/dsh-lsp', '@deepseek-ai/dsh-lsp-stdio', '@deepseek-ai/dsh-tool-lsp']
                  and row.get('enabled')]
        assert not active, active
        evidence['defaultMigrationDidNotReenable'] = True
        evidence['enable'] = emulator.rpc('pluginManager/setBundleEnabled', {'name': NAME, 'enabled': True})
        assert evidence['enable']['application'] in ['applied', 'restart-required'], evidence['enable']
        emulator.stop(); emulator.start(); evidence['enabledRestartReadyMs'] = emulator.ready('normal')
        evidence['afterEnabledRestart'] = bundle(emulator); assert evidence['afterEnabledRestart']['enabled']
        active = [row for row in emulator.rpc('pluginManager/listPlugins', {})
                  if row['moduleName'] == '@deepseek-ai/dsh-lsp-stdio' and row.get('enabled')]
        assert len(active) == 1 and active[0].get('fiberPhase') is not None, active
        evidence['officialProviderActive'] = True
    finally:
        try:
            if saved:
                emulator.stop()
                for path in saved: emulator.app('cp ' + path + suffix + ' ' + path + ' && rm -f ' + path + suffix)
                emulator.start(); evidence['restoredReadyMs'] = emulator.ready('normal')
                after = {path: hashlib.sha256(agent['read_bytes'](emulator, path)).hexdigest() for path in saved}
                assert before == after, (before, after)
                evidence['configurationHashesRestored'] = after
        finally: output.write_text(json.dumps(evidence, indent=2) + '\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('target'); parser.add_argument('output', type=Path); options = parser.parse_args()
    emulator = support['Emulator'](options.target, 19643); forward = ('tcp:19643', 'tcp:19592')
    emulator.hdc('fport', *forward)
    try: run(emulator, options.output)
    finally: emulator.hdc('fport', 'rm', *forward)
