"""Probe the shipped require-builtin addon and actual Inspector in native Host/Worker."""
import argparse
import hashlib
import json
from pathlib import Path
import runpy
import time
import uuid

agent = runpy.run_path(str(Path(__file__).with_name('emulator-agent-continuation.py')))
support = agent['support']
lsp = runpy.run_path(str(Path(__file__).with_name('emulator-lsp-lifecycle.py')))


def run(emulator, output):
    name = 'mh-builtin-probe-' + uuid.uuid4().hex[:10]
    patch = 'alpine/native-benchmark-home/cordis.patch.yml'
    module = 'alpine/tmp/' + name + '.mjs'; result = 'alpine/tmp/' + name + '.json'
    absolute = support['WORKSPACE'].rsplit('/', 1)[0] + '/tmp/' + name
    evidence = {'fixture': name}; originals = {}
    try:
        emulator.ready('normal')
        assert emulator.app('test ! -e ' + patch + ' && printf EMPTY') == 'EMPTY'
        assert not emulator.rpc('credentials/describe', {'refs': ['DEEPSEEK_API_KEY']})['DEEPSEEK_API_KEY']['configured']
        for path in ['mobile-harness-boot.json', 'alpine/native-benchmark-home/profiles/web/package.json', 'alpine/native-benchmark-home/profiles/web/pnpm-lock.yaml']:
            originals[path] = agent['read_bytes'](emulator, path)
        source = Path(__file__).with_name('fixtures').joinpath('builtin-binding-probe.mjs').read_text().replace('__MH_PROBE_RESULT__', json.dumps(absolute + '.json'))
        emulator.stop()
        lsp['restore_bytes'](emulator, module, source.encode(), '/data/local/tmp/' + name + '-module')
        lsp['restore_bytes'](emulator, patch, ('- insert:\n    - id: ' + name + '\n      name: ' + json.dumps('file://' + absolute + '.mjs') + '\n').encode(), '/data/local/tmp/' + name + '-patch')
        emulator.start(); evidence['readyMs'] = emulator.ready('normal')
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if emulator.app('test -e ' + result + ' && printf PRESENT') == 'PRESENT': break
            time.sleep(.2)
        evidence['probe'] = json.loads(agent['read_bytes'](emulator, result))
        assert all(row['loaded'] for row in evidence['probe']['host']['internals']), evidence['probe']
        assert all(row['loaded'] for row in evidence['probe']['worker']['binding']['internals']), evidence['probe']
        assert evidence['probe']['worker']['inspector']['result']['value'] == 42, evidence['probe']
        evidence['actualNativeBindingAndInspectorPassed'] = True
    finally:
        try:
            if originals:
                emulator.stop(); emulator.app('rm -f ' + patch + ' ' + module + ' ' + result)
                for index, (path, body) in enumerate(originals.items()): lsp['restore_bytes'](emulator, path, body, '/data/local/tmp/' + name + '-' + str(index))
                emulator.start(); evidence['restoredReadyMs'] = emulator.ready('normal')
                evidence['configurationHashesRestored'] = {path: hashlib.sha256(agent['read_bytes'](emulator, path)).hexdigest() for path in originals}
                assert evidence['configurationHashesRestored'] == {path: hashlib.sha256(body).hexdigest() for path, body in originals.items()}
        finally: output.write_text(json.dumps(evidence, indent=2) + '\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('target'); parser.add_argument('output', type=Path); options = parser.parse_args()
    emulator = support['Emulator'](options.target, 19643); forward = ('tcp:19643', 'tcp:19592')
    emulator.hdc('fport', *forward)
    try: run(emulator, options.output)
    finally: emulator.hdc('fport', 'rm', *forward)
