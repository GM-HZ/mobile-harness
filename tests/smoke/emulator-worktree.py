"""Exercise official RC.4 Git worktrees with default refusal and explicit session permission."""
import argparse
import json
import os
from pathlib import Path
import re
import runpy
import time
import uuid

optional = runpy.run_path(str(Path(__file__).with_name('emulator-optional-iteration.py')))
agent = optional['agent']; support = optional['support']; toolkit = optional['toolkit']


def full_permission(emulator, sid):
    response = emulator.rpc('commands/execute', {'agentId': sid, 'line': '/permission danger-full-access', 'submittedAttachments': []})
    modes = [r['data']['mode'] for r in support['events'](emulator, sid) if r['type'] == 'sandbox/mode']
    assert modes[-1] == 'danger-full-access', (response, modes)
    return response


def helpers_reaped(emulator):
    rows = [json.loads(line) for line in emulator.app('cat alpine/tmp/dsh-native-timeline.log').splitlines()]
    started = {r['pid'] for r in rows if r['event'] == 'host-subprocess-started'}
    ended = {r['pid'] for r in rows if r['event'] == 'host-subprocess-reaped'}
    assert started and started <= ended, (started, ended)
    return len(started)


def verify(emulator, evidence, name):
    app = 'alpine/workspace-native/' + name
    repo = support['WORKSPACE'] + '/' + name
    marker = 'WORKTREEBASE' + uuid.uuid4().hex.upper()
    modified = 'WORKTREEMODIFIED' + uuid.uuid4().hex.upper()
    sid = support['session'](emulator, True)
    evidence['sessionId'] = sid
    try:
        agent['tool'](emulator, sid, 'working_directory', {'cd': repo})
        agent['tool'](emulator, sid, 'write', {'file_path': 'tracked.txt', 'content': marker})
        command = 'git init -q && git add tracked.txt && git -c user.name=MHFixture -c user.email=fixture@example.invalid commit -q -m fixture'
        args = {'command': command, 'description': 'Initialize only the owned worktree acceptance repository',
                'sandbox_permissions': 'danger-full-access', 'justification': '仅为当前回归夹具初始化 Git，精确命令单次审批。'}
        with toolkit['approval']['approval_events'](emulator) as events:
            calls, results = toolkit['prompt'](emulator, sid, 'Call bash exactly once with precisely ' + json.dumps(args)
                + '. Do not use other tools or retry.', events, command)
        assert len(calls) == len(results) == 1 and json.loads(calls[0]['arguments']) == args, calls
        assert not results[0]['isError'], results
        assert agent['read_bytes'](emulator, app + '/tracked.txt') == marker.encode()
        result, _ = agent['tool'](emulator, sid, 'create_worktree', {'name': 'must-refuse'}, expect_error=True)
        assert 'no sandbox backend is usable' in toolkit['texts']([result]), result
        assert emulator.app(f'test ! -e {app}/.agents && printf ABSENT') == 'ABSENT'
        evidence['defaultPolicyRefusedWithoutMutation'] = True
        evidence['explicitOwnedSessionPermission'] = full_permission(emulator, sid)
        result, rows = agent['tool'](emulator, sid, 'create_worktree', {'name': 'acceptance'})
        created = json.loads(toolkit['texts']([result])); evidence['created'] = created
        checkout = repo + '/.agents/worktrees/acceptance'
        checkout_app = app + '/.agents/worktrees/acceptance'
        assert created['path'] == checkout and created['branch'] == 'acceptance' and created['repositoryRoot'] == repo, created
        assert re.fullmatch('[a-f0-9]{40}', created['baseCommit']), created
        assert any(r['type'] == 'plugin:worktree/created' and r.get('ignorable') is True and r['data'] == created for r in rows), rows[-5:]
        assert agent['read_bytes'](emulator, checkout_app + '/tracked.txt') == marker.encode()
        evidence['gitControlFile'] = agent['read_bytes'](emulator, checkout_app + '/.git').decode()
        assert repo + '/.git/worktrees/' in evidence['gitControlFile'], evidence['gitControlFile']
        agent['tool'](emulator, sid, 'write', {'file_path': 'tracked.txt', 'content': modified})
        assert agent['read_bytes'](emulator, checkout_app + '/tracked.txt') == modified.encode()
        assert agent['read_bytes'](emulator, app + '/tracked.txt') == marker.encode()
        # Git itself must report the same checkout and commit, not just copied files.
        result, _ = agent['tool'](emulator, sid, 'bash', {
            'command': 'git rev-parse --show-toplevel && git branch --show-current && git rev-parse HEAD',
            'description': 'Verify owned linked checkout identity'})
        text = toolkit['texts']([result])
        assert checkout in text and 'acceptance' in text and created['baseCommit'] in text, text
        evidence['nativePathsGitIdentityAndIndependentBytes'] = True
        evidence['helpersReapedBeforeRestart'] = helpers_reaped(emulator)
        emulator.stop(); emulator.start(); evidence['restartReadyMs'] = emulator.ready('normal')
        result, _ = agent['tool'](emulator, sid, 'working_directory', {})
        assert checkout in toolkit['texts']([result]), result
        result, _ = agent['tool'](emulator, sid, 'read', {'file_path': 'tracked.txt'})
        assert modified in toolkit['texts']([result]), result
        assert agent['read_bytes'](emulator, checkout_app + '/tracked.txt') == modified.encode()
        evidence['sameSessionCheckoutAcrossRestart'] = True
        emulator.rpc('workspace/archiveSession', {'request': {'sessionId': sid}})
        time.sleep(1)
        assert agent['read_bytes'](emulator, checkout_app + '/tracked.txt') == modified.encode()
        evidence['dirtyArchivedCheckoutRetained'] = True
        # A clean second checkout must be reclaimed without deleting its branch.
        clean = support['session'](emulator, True); evidence['cleanSessionId'] = clean
        full_permission(emulator, clean)
        agent['tool'](emulator, clean, 'working_directory', {'cd': repo})
        result, _ = agent['tool'](emulator, clean, 'create_worktree', {'name': 'clean-acceptance'})
        clean_path = json.loads(toolkit['texts']([result]))['path']
        assert clean_path == repo + '/.agents/worktrees/clean-acceptance'
        emulator.rpc('workspace/archiveSession', {'request': {'sessionId': clean}})
        deadline = time.monotonic() + 25
        while emulator.app(f'test -e {app}/.agents/worktrees/clean-acceptance && printf PRESENT || printf ABSENT') != 'ABSENT':
            if time.monotonic() > deadline: raise AssertionError('Clean archived worktree was not reclaimed')
            time.sleep(.15)
        assert emulator.app(f'test -f {app}/.git/refs/heads/clean-acceptance && printf RETAINED') == 'RETAINED'
        evidence['cleanArchivedCheckoutReclaimedBranchRetained'] = True
        evidence['helpersReapedAfterRestart'] = helpers_reaped(emulator)
    finally:
        emulator.rpc('session/cancel', {'request': {'sessionId': sid}})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('target'); parser.add_argument('output', type=Path)
    options = parser.parse_args()
    if not os.environ.get('MH_TEST_DEEPSEEK_API_KEY'): parser.error('MH_TEST_DEEPSEEK_API_KEY is required')
    emulator = support['Emulator'](options.target, 19643)
    forward = ('tcp:19643', 'tcp:19592'); emulator.hdc('fport', *forward)
    try: optional['run'](emulator, options.output, 'custom', verify, ['@deepseek-ai/dsh-experimental-tool-worktree'])
    finally: emulator.hdc('fport', 'rm', *forward)
