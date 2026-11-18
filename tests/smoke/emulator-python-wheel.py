"""Install and execute a pinned public CPython musllinux wheel through approved DSH Bash."""

import argparse
import json
import os
from pathlib import Path
import runpy
import tempfile
import uuid

toolkit = runpy.run_path(str(Path(__file__).with_name('emulator-toolkit.py')))
support = toolkit['support']
WHEEL = 'xxhash-3.6.0-cp312-cp312-musllinux_1_2_aarch64.whl'
SHA256 = 'bd17fede52a17a4f9a7bc4472a5867cb0b160deeb431795c0e4abe158bc784e9'
RESULT = 'HARMONY_NATIVE_PYTHON:'
SCRIPT = f'''set -eu
cd "$1"
printf '%s\\n' 'xxhash==3.6.0 --hash=sha256:{SHA256}' > requirements.txt
python3 -m venv .venv
.venv/bin/python -m pip --isolated install \\
  --disable-pip-version-check --no-cache-dir --timeout 8 --retries 1 \\
  --index-url https://pypi.org/simple --only-binary :all: --no-deps --require-hashes \\
  --report install.json -r requirements.txt
.venv/bin/python - <<'PY'
from importlib.metadata import version
import json
from pathlib import Path
import sys
from urllib.parse import urlsplit
import xxhash
import xxhash._xxhash as native

assert sys.prefix != sys.base_prefix
extension = Path(native.__file__)
assert extension.is_relative_to(Path(sys.prefix)) and extension.suffix == '.so'
archive, = json.loads(Path('install.json').read_text())['install']
download = archive['download_info']
url = urlsplit(download['url'])
assert url.scheme == 'https' and url.hostname == 'files.pythonhosted.org'
assert url.path.endswith('/{WHEEL}')
assert download['archive_info']['hashes']['sha256'] == '{SHA256}'
digest = xxhash.xxh64(b'').hexdigest()
assert digest == 'ef46db3751d8e999'
print('{RESULT}' + json.dumps(dict(wheel=Path(url.path).name, sha256=download['archive_info']['hashes']['sha256'],
     distribution=version('xxhash'), binary=extension.name, digest=digest, isolated=True)))
PY
'''


def run(device, output):
    name = 'mh-native-wheel-' + uuid.uuid4().hex[:10]
    folder = 'alpine/workspace-native/' + name
    remote = '/data/local/tmp/' + name + '.sh'
    evidence = {}
    workspace = None
    session = None
    bridge = ('tcp:19643', 'tcp:19592')
    assert 'Forwardport result:OK' in device.hdc('fport', *bridge)
    try:
        device.ready('normal')
        device.app('mkdir ' + folder)
        with tempfile.TemporaryDirectory() as directory:
            fixture = Path(directory) / 'probe.sh'
            fixture.write_text(SCRIPT)
            assert 'FileTransfer finish' in device.hdc('file', 'send', str(fixture), remote)
        device.app(f'cp {remote} {folder}/probe.sh')
        path = support['WORKSPACE'] + '/' + name
        workspace = device.rpc('workspace/create', {'request': {'path': path}})['workspace']['workspaceId']
        with support['model_key'](device):
            session = device.rpc('session/create', {'request': {'workspaceId': workspace}})['sessionId']
            device.rpc('session/selectModel', {'request': {'sessionId': session, 'provider': 'deepseek-official',
                       'model': 'deepseek-flash', 'reasoningEffort': 'off'}})
            command = 'bash ./probe.sh .'
            args = {'command': command, 'description': 'Install and check the pinned public wheel in this temporary venv',
                    'timeoutMs': 150000, 'sandbox_permissions': 'danger-full-access',
                    'justification': 'Run only the owned temporary wheel fixture on the emulator.'}
            with toolkit['approval']['approval_events'](device) as events:
                calls, results = toolkit['prompt'](device, session,
                    'Call bash exactly once with this JSON. Report its result and stop: ' + json.dumps(args),
                    events, command, timeout=180)
            assert len(calls) == len(results) == 1 and calls[0]['name'] == 'bash', calls
            assert calls[0]['arguments'] and json.loads(calls[0]['arguments']) == args
            body = toolkit['texts'](results)
            evidence['toolOutput'] = body
            assert not results[0]['isError'], body
            line, = [line for line in body.splitlines() if line.startswith(RESULT)]
            evidence['wheelProbe'] = value = json.loads(line[len(RESULT):])
            assert value['wheel'] == WHEEL and value['sha256'] == SHA256
            assert value['distribution'] == '3.6.0' and value['digest'] == 'ef46db3751d8e999'
            assert value['isolated'] and value['binary'].endswith('.so')
            evidence['exactBashApproval'] = True
        evidence['testCredentialRemoved'] = True
    finally:
        try:
            if session:
                device.rpc('workspace/archiveSession', {'request': {'sessionId': session}})
            if workspace:
                assert device.rpc('workspace/delete', {'request': {'workspaceId': workspace}}) == {'deleted': True}
        finally:
            device.app(f'rm -rf {folder}')
            device.hdc('shell', 'rm', '-f', remote)
            device.hdc('fport', 'rm', *bridge)
            output.write_text(json.dumps(evidence, indent=2) + '\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('target')
    parser.add_argument('output', type=Path)
    options = parser.parse_args()
    if not os.environ.get('MH_TEST_DEEPSEEK_API_KEY'):
        parser.error('MH_TEST_DEEPSEEK_API_KEY is required')
    run(support['Emulator'](options.target, 19643), options.output)
