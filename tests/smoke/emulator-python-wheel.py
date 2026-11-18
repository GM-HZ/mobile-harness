"""Install and execute a pinned public CPython musllinux wheel through approved DSH Bash."""

import argparse
import json
import os
import re
from pathlib import Path
import runpy
import tempfile
import time
import uuid

toolkit = runpy.run_path(str(Path(__file__).with_name('emulator-toolkit.py')))
support = toolkit['support']
WHEEL = 'xxhash-3.6.0-cp312-cp312-musllinux_1_2_aarch64.whl'
SHA256 = 'bd17fede52a17a4f9a7bc4472a5867cb0b160deeb431795c0e4abe158bc784e9'
RESULT = 'HARMONY_NATIVE_PYTHON:'
SCRIPT = f'''set -eu
cd "$1"
printf '%s\\n' 'xxhash==3.6.0 --hash=sha256:{SHA256}' > requirements.txt
python3 -m venv --copies .venv
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


def verify_native_suite(value):
    expected = {
        'numpy': ('numpy-2.2.6-cp312-cp312-musllinux_1_2_aarch64.whl',
                  '37c0ca431f82cd5fa716eca9506aefcabc247fb27ba69c5062a6d3ade8cf8f49', '2.2.6'),
        'orjson': ('orjson-3.11.4-cp312-cp312-musllinux_1_2_aarch64.whl',
                   '149d95d5e018bdd822e3f38c103b1a7c91f88d38a88aada5c4e9b3a73a244241', '3.11.4'),
    }
    assert value['wheels'] == {name: dict(zip(('filename','sha256','version'), row)) for name, row in expected.items()}
    assert value['isolated'] and value['arch'] == 'aarch64'
    assert len(value['artifacts']) == 3 and all(item.endswith('.so') for item in value['artifacts'])
    assert any('openblas' in item for item in value['libraries'])
    assert value['solution'] == [2.0, 3.0] and json.loads(value['nativeJson']) == {'solution': [2.0, 3.0], 'label': '鸿蒙'}


def wait_for_background_probe(device, session, job, folder, timeout=300):
    deadline = time.monotonic()+timeout
    while time.monotonic() < deadline:
        settled = next((row['data'] for row in support['events'](device, session)
                        if row['type'] == 'job/settled' and row['data']['jobId'] == job), None)
        if settled:
            assert settled['owner'] == session and settled['status'] == 'completed', settled
            assert settled['producerReported'] and settled['detail'] == 'exit code: 0', settled
            result = json.loads(device.app('cat ' + folder + '/probe-result.json'))
            return result, {'jobId': job, 'status': settled['status'], 'detail': settled['detail'],
                            'durationMs': settled['finishedAt']-settled['startedAt']}
        time.sleep(.75)
    raise AssertionError('The native wheel background job did not settle')


def archive_fixture(device, session):
    deadline = time.monotonic()+10
    while time.monotonic() < deadline:
        device.rpc('session/cancel', {'request': {'sessionId': session}})
        try:
            device.rpc('workspace/archiveSession', {'request': {'sessionId': session}})
            return
        except RuntimeError as error:
            if str(error) != 'workspace/archiveSession: workspace/session-active':
                raise
        time.sleep(.25)
    raise AssertionError('The owned wheel fixture session could not be archived')


def run(device, output, port, native_suite):
    name = 'mh-native-wheel-' + uuid.uuid4().hex[:10]
    folder = 'alpine/workspace-native/' + name
    remote = '/data/local/tmp/' + name + '.sh'
    evidence = {}
    workspace = None
    session = None
    command = 'bash ./probe.sh .'
    bridge = (f'tcp:{port}', 'tcp:19592')
    assert 'Forwardport result:OK' in device.hdc('fport', *bridge)
    try:
        device.ready('normal')
        device.app('mkdir ' + folder)
        with tempfile.TemporaryDirectory() as directory:
            fixture = Path(directory) / 'probe.sh'
            fixture.write_text((Path(__file__).with_name('fixtures')/'python-native-wheels.sh').read_text()
                               if native_suite else SCRIPT)
            assert 'FileTransfer finish' in device.hdc('file', 'send', str(fixture), remote)
        device.app(f'cp {remote} {folder}/probe.sh')
        path = support['WORKSPACE'] + '/' + name
        workspace = device.rpc('workspace/create', {'request': {'path': path}})['workspace']['workspaceId']
        with support['model_key'](device):
            session = device.rpc('session/create', {'request': {'workspaceId': workspace}})['sessionId']
            device.rpc('session/selectModel', {'request': {'sessionId': session, 'provider': 'deepseek-official',
                       'model': 'deepseek-flash', 'reasoningEffort': 'off'}})
            args = {'command': command, 'description': 'Install and check the pinned public wheels in this temporary venv',
                    'sandbox_permissions': 'danger-full-access',
                    'justification': 'Run only the owned temporary wheel fixture on the emulator.'}
            if native_suite:
                args['run_in_background'] = True
            else:
                args['timeoutMs'] = 150000
            with toolkit['approval']['approval_events'](device) as events:
                instructions = ('Call bash exactly once with this JSON. Reply with the job ID when it starts. '
                                'Do not call job_output, job_wait, or any other tool: ' if native_suite else
                                'Call bash exactly once with this JSON. Report its result and stop: ')
                calls, results = toolkit['prompt'](device, session, instructions + json.dumps(args),
                    events, command, timeout=180, return_on_tool_result=native_suite)
            assert len(calls) == len(results) == 1 and calls[0]['name'] == 'bash', calls
            assert calls[0]['arguments'] and json.loads(calls[0]['arguments']) == args
            body = toolkit['texts'](results)
            evidence['toolOutput'] = body
            assert not results[0]['isError'], body
            if native_suite:
                match = re.search(r'started background job (bash-[0-9a-f]{16})', body)
                assert match, body
                value, evidence['backgroundJob'] = wait_for_background_probe(device, session, match[1], folder)
                verify_native_suite(value)
            else:
                line, = [line for line in body.splitlines() if line.startswith(RESULT)]
                value = json.loads(line[len(RESULT):])
                assert value['wheel'] == WHEEL and value['sha256'] == SHA256
                assert value['distribution'] == '3.6.0' and value['digest'] == 'ef46db3751d8e999'
                assert value['isolated'] and value['binary'].endswith('.so')
            evidence['wheelProbe'] = value
            evidence['exactBashApproval'] = True
        evidence['testCredentialRemoved'] = True
    finally:
        try:
            if session:
                rows = support['events'](device, session)
                settled = {row['data']['jobId'] for row in rows if row['type'] == 'job/settled'}
                for row in rows:
                    if row['type'] != 'job/registered':
                        continue
                    data = row['data']
                    if data['owner'] == session and data['label'] == command and data['jobId'] not in settled:
                        device.rpc('job/kill', {'request': {'sessionId': session, 'jobId': data['jobId']}})
                archive_fixture(device, session)
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
    parser.add_argument('--host-port', type=int, default=19643)
    parser.add_argument('--native-suite', action='store_true', help='Run NumPy/OpenBLAS and orjson from pinned public wheels')
    options = parser.parse_args()
    if not os.environ.get('MH_TEST_DEEPSEEK_API_KEY'):
        parser.error('MH_TEST_DEEPSEEK_API_KEY is required')
    run(support['Emulator'](options.target, options.host_port), options.output, options.host_port, options.native_suite)
