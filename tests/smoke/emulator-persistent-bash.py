"""Exercise the official DSH Minimal Bash tool on the real HarmonyOS pipe backend."""

import argparse
import json
import os
from pathlib import Path
import runpy
import time
import uuid

agent = runpy.run_path(str(Path(__file__).with_name('emulator-agent-continuation.py')))
support = agent['support']
toolkit = agent['toolkit']
full_permission = runpy.run_path(str(Path(__file__).with_name('emulator-worktree.py')))['full_permission']
restore_bytes = runpy.run_path(str(Path(__file__).with_name('emulator-lsp-lifecycle.py')))['restore_bytes']
PROFILE = 'alpine/native-benchmark-home/profiles/web/cordis.patch.yml'
TRACE = 'alpine/tmp/dsh-native-timeline.log'


def shell(device, session, command, *, error=False):
    calls, results, _ = agent['prompt'](device, session,
        'Call bash exactly once with ' + json.dumps({'command': command}) +
        '. Use no other tools, and report the single result.', allow_error=error)
    assert len(calls) == len(results) == 1 and calls[0]['name'] == 'bash', calls
    assert json.loads(calls[0]['arguments']) == {'command': command}
    assert results[0]['isError'] == error
    return toolkit['texts'](results)


def wait_for(check, description, seconds=12):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if result := check():
            return result
        time.sleep(.12)
    raise AssertionError('Did not observe ' + description)


def process_sets(device):
    rows = [json.loads(line) for line in device.app('cat ' + TRACE).splitlines()]
    started = {row['id'] for row in rows if row['event'] == 'persistent-bash-started'}
    reaped = {row['id'] for row in rows if row['event'] == 'persistent-bash-reaped'}
    return started, reaped


def run(device, output, port, expect_absent):
    forward = (f'tcp:{port}', 'tcp:19592')
    assert 'Forwardport result:OK' in device.hdc('fport', *forward)
    original = None
    workspace = None
    sessions = []
    name = 'mh-pipe-bash-' + uuid.uuid4().hex[:10]
    app = 'alpine/workspace-native/' + name
    evidence = {}
    try:
        device.start()
        device.ready('normal')
        catalog = device.rpc('agentPresets/list', {})
        evidence['catalog'] = catalog
        assert device.rpc('permissionPresets/catalog', {})['defaultPreset'] == 'workspace-write'
        if expect_absent:
            assert 'minimal' not in json.dumps(catalog)
            evidence['minimalAdvertised'] = False
            return
        original = agent['read_bytes'](device, PROFILE)
        device.app('mkdir ' + app)
        workspace = device.rpc('workspace/create', {'request': {'path': support['WORKSPACE'] + '/' + name}})['workspace']['workspaceId']
        with support['model_key'](device):
            for _ in range(2):
                response = device.rpc('session/create', {'request': {'workspaceId': workspace, 'agentPreset': 'minimal'}})
                assert response['agentPreset'] == 'minimal', response
                sid = response['sessionId']
                sessions.append(sid)
                device.rpc('session/selectModel', {'request': {'sessionId': sid, 'provider': 'deepseek-official',
                           'model': 'deepseek-flash', 'reasoningEffort': 'off'}})
            owner, other = sessions
            evidence['sessions'] = sessions
            before, _ = process_sets(device)
            denied = shell(device, owner, "printf forbidden > forbidden.txt", error=True)
            assert 'requires a sandbox backend' in denied, denied
            assert device.app('test ! -f ' + app + '/forbidden.txt && printf ABSENT') == 'ABSENT'
            assert process_sets(device)[0] == before
            evidence['defaultDeniedWithoutSpawning'] = True
            full_permission(device, owner)
            full_permission(device, other)
            marker = 'HARMONY_' + uuid.uuid4().hex[:12].upper()
            first = shell(device, owner, 'mkdir state; cd state; export MH_PIPE_STATE=' + marker +
                '; mh_pipe_value() { printf "%s\\n" "$MH_PIPE_STATE"; }; printf "READY\\n"')
            assert 'READY\n' in first and '[Command finished with exit code 0]' in first, first
            pids, reaped = process_sets(device)
            owned, = pids - before
            assert owned not in reaped
            again = shell(device, owner, 'pwd; mh_pipe_value; printf "ERR\\n" >&2; false')
            assert '/' + name + '/state' in again and marker in again and 'ERR' in again
            assert '[Command finished with exit code 1]' in again
            assert '__DSH_' not in first + again and process_sets(device)[0] == pids
            isolated = shell(device, other, 'pwd; printf "%s\\n" "${MH_PIPE_STATE-unset}"; type -t mh_pipe_value || true')
            assert '/' + name + '\n' in isolated and 'unset\n' in isolated and marker not in isolated
            evidence['ownerStateAndNonzeroStatus'] = True
            evidence['independentOwner'] = True
            policy_event_count = sum(row['type'] == 'sandbox/mode' for row in support['events'](device, owner))
            try:
                outcome = device.rpc('commands/execute', {'agentId': owner, 'line': '/permission workspace-write', 'submittedAttachments': []})
                evidence['policyChangeResult'] = outcome
            except RuntimeError as error:
                evidence['policyChangeResult'] = str(error)
            assert sum(row['type'] == 'sandbox/mode' for row in support['events'](device, owner)) == policy_event_count
            evidence['permissionChangeFenced'] = True
            launched = shell(device, owner, '(sleep 1; printf "BACKGROUND\\n" > job.txt) & export MH_PIPE_JOB=$!; printf "STARTED\\n"')
            assert 'STARTED' in launched and '[Command finished with exit code 0]' in launched
            collected = shell(device, owner, 'wait "$MH_PIPE_JOB" && cat job.txt')
            assert 'BACKGROUND\n' in collected and '[Command finished with exit code 0]' in collected
            eof = shell(device, owner, 'if read -r line; then printf INPUT; else printf "EOF\\n"; fi')
            assert 'EOF\n' in eof and '[Command finished with exit code 0]' in eof
            evidence['backgroundJobAndEmptyStdin'] = True

            previous = support['events'](device, owner)
            cutoff = previous[-1]['seq']
            command = 'printf ready > cancel-started.txt; sleep 20; printf wrong > cancelled.txt'
            device.rpc('session/prompt', {'request': {'sessionId': owner, 'requestId': str(uuid.uuid4()), 'mode': 'queue',
                       'content': [{'type': 'text', 'text': 'Call bash once with exactly ' + json.dumps({'command': command}) +
                                       '. Use no other tools. The acceptance harness cancels it after the startup marker.'}]}})
            wait_for(lambda: device.app('test -f ' + app + '/state/cancel-started.txt && printf READY') == 'READY',
                     'a real running Bash command', 45)
            assert device.rpc('session/cancel', {'request': {'sessionId': owner}})['accepted']
            ended = wait_for(lambda: next((row for row in support['events'](device, owner)
                    if row['seq'] > cutoff and row['type'] == 'turn/end'), None), 'cancelled turn')
            cancel_reason = {'kind': 'aborted', 'reason': {'kind': 'user'}}
            assert ended['data']['reason'] == cancel_reason, ended
            wait_for(lambda: owned in process_sets(device)[1], 'owned shell reap')
            assert device.app('test ! -f ' + app + '/state/cancelled.txt && printf ABSENT') == 'ABSENT'
            reset = shell(device, owner, 'pwd; printf "%s\\n" "${MH_PIPE_STATE-unset}"')
            assert '/' + name + '\n' in reset and 'unset\n' in reset
            exit_result = shell(device, owner, 'exit 7')
            assert '[shell exited: code 7]' in exit_result and 'shell was reset' in exit_result
            evidence['cancellationReapedAndReset'] = True
            evidence['cancelTurnReason'] = cancel_reason
            evidence['exitCodeAndReset'] = True
            assert '[Command finished with exit code 0]' in shell(device, other, 'printf "OTHER_ALIVE\\n"')
            assert '[shell exited: code 0]' in shell(device, other, 'exit 0')
            def all_shells_reaped():
                started, reaped = process_sets(device)
                return len(started - before) == 3 and started - before <= reaped

            wait_for(all_shells_reaped, 'all three test shells reaped')
            evidence['shellsStartedAndReaped'] = 3
        evidence['testCredentialRemoved'] = True
    finally:
        try:
            for session in sessions:
                device.rpc('session/cancel', {'request': {'sessionId': session}})
                device.rpc('workspace/archiveSession', {'request': {'sessionId': session}})
            if workspace:
                assert device.rpc('workspace/delete', {'request': {'workspaceId': workspace}}) == {'deleted': True}
                device.app('rm -rf ' + app)
            if original is not None:
                if agent['read_bytes'](device, PROFILE) != original:
                    device.stop()
                    restore_bytes(device, PROFILE, original, '/data/local/tmp/' + name)
                    device.start()
                    device.ready('normal')
                assert agent['read_bytes'](device, PROFILE) == original
                evidence['profileRestored'] = True
        finally:
            device.hdc('fport', 'rm', *forward)
            output.write_text(json.dumps(evidence, indent=2) + '\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('target')
    parser.add_argument('output', type=Path)
    parser.add_argument('--port', type=int, default=19643)
    parser.add_argument('--expect-absent', action='store_true')
    args = parser.parse_args()
    if not args.expect_absent and not os.environ.get('MH_TEST_DEEPSEEK_API_KEY'):
        parser.error('MH_TEST_DEEPSEEK_API_KEY is required')
    run(support['Emulator'](args.target, args.port), args.output, args.port, args.expect_absent)
