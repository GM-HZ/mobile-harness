"""Verify the official Forge worktree restore RPC and cancellation with real Git."""
import argparse
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import runpy
import socket
import time
from urllib.parse import urlsplit
import uuid

worktree = runpy.run_path(str(Path(__file__).with_name('emulator-worktree.py')))
agent, support, toolkit = (worktree[key] for key in ('agent', 'support', 'toolkit'))
lsp = runpy.run_path(str(Path(__file__).with_name('emulator-lsp-lifecycle.py')))
PROFILE = 'alpine/native-benchmark-home/profiles/web'
PATCH = 'alpine/native-benchmark-home/cordis.patch.yml'
FORGE = '@deepseek-ai/dsh-experimental-forge-bundle'
CATALOG = {
    '@deepseek-ai/dsh-experimental-ralph-bundle': '@deepseek-ai/dsh-tool-ralph',
    '@deepseek-ai/dsh-experimental-session-search': '@deepseek-ai/dsh-tool-session-query',
    '@deepseek-ai/dsh-experimental-tool-worktree': '@deepseek-ai/dsh-experimental-worktree',
    FORGE: '@deepseek-ai/dsh-experimental-client-ui-forge',
}


def wait_until(read, message, timeout=20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = read()
        if value:
            return value
        time.sleep(.1)
    raise AssertionError(message)


def bash(emulator, session, command):
    result, _ = agent['tool'](emulator, session, 'bash', {
        'command': command, 'description': 'Run Git only in the owned restoration fixture',
    })
    return toolkit['texts']([result]).strip()


def folder_session(emulator, repo):
    workspace = emulator.rpc('workspace/create', {'request': {'path': repo}})['workspace']
    session = emulator.rpc('session/create', {'request': {'workspaceId': workspace['workspaceId']}})['sessionId']
    emulator.rpc('session/selectModel', {'request': {
        'sessionId': session, 'provider': 'deepseek-official', 'model': 'deepseek-flash', 'reasoningEffort': 'off',
    }})
    worktree['full_permission'](emulator, session)
    return session


def forge_actions(emulator, session):
    return [row['data']['action'] for row in support['events'](emulator, session)
            if row['type'] == 'plugin:client-ui-forge/worktree']


def timeline(emulator):
    return [json.loads(line) for line in emulator.app('cat alpine/tmp/dsh-native-timeline.log').splitlines()]


def cancel_restore(emulator, session, folder, evidence):
    endpoint = urlsplit(emulator.url)
    connection = http.client.HTTPConnection(endpoint.hostname, endpoint.port, timeout=8)
    args = {'sessionId': session}
    body = json.dumps({'type': 'client-request', 'rpcId': str(uuid.uuid4()), 'method': 'forgePanel/restoreWorktree',
                       'payload': {'args': args}})
    before = len(timeline(emulator))
    actions = forge_actions(emulator, session)
    try:
        connection.request('POST', '/api/forgePanel/restoreWorktree', body,
                           headers={'Content-Type': 'application/json', 'Host': '127.0.0.1:19592',
                                    'Cookie': emulator.cookie()})
        wait_until(lambda: emulator.app(f'test -f {folder}/reset-started && printf READY') == 'READY',
                   'The real provider did not launch the gated restore checkout')
        rows = timeline(emulator)[before:]
        started = {row['pid'] for row in rows if row['event'] == 'host-subprocess-started'}
        ended = {row['pid'] for row in rows if row['event'] == 'host-subprocess-reaped'}
        active = started - ended
        assert len(active) == 1, rows
        evidence['gatedCheckoutActivePids'] = sorted(active)
        start = time.monotonic()
        connection.sock.shutdown(socket.SHUT_RDWR)
        connection.close()
        wait_until(lambda: active <= {row['pid'] for row in timeline(emulator)[before:]
                                      if row['event'] == 'host-subprocess-reaped'},
                   'The production provider did not reap the cancelled checkout', timeout=12)
        evidence['cancelToReapedMs'] = round((time.monotonic() - start) * 1000)
        assert forge_actions(emulator, session)[len(actions):] == ['restoring']
        evidence['cancelledSessionLoggedRestoringWithoutRestored'] = True
    finally:
        connection.close()


def check_restore(emulator, folder, repo, evidence, sessions):
    commit_template = 'git -c user.name=MHFixture -c user.email=fixture@example.invalid commit -qm '
    initializer = folder_session(emulator, repo)
    sessions.append(initializer)
    agent['tool'](emulator, initializer, 'write', {'file_path': 'tracked.txt', 'content': 'BASE'})
    base = bash(emulator, initializer, 'git init -q && git add tracked.txt && ' + commit_template + 'base && git rev-parse HEAD')
    assert re.fullmatch('[a-f0-9]{40}', base), base
    sessions.remove(initializer)

    session = folder_session(emulator, repo)
    sessions.append(session)
    evidence['sessionId'] = session
    emulator.rpc('forgePanel/requestWorktree', {'sessionId': session, 'from': None})
    agent['prompt'](emulator, session, 'Reply with OK. Use no tools.')
    events = support['events'](emulator, session)
    created, = [row['data'] for row in events if row['type'] == 'plugin:worktree/created']
    branch = created['branch']
    checkout = folder + '/.agents/worktrees/' + branch
    assert re.fullmatch('[a-z0-9-]+', branch), branch
    assert created['baseCommit'] == base and created['path'] == repo + '/.agents/worktrees/' + branch, created
    evidence['created'] = created
    agent['tool'](emulator, session, 'write', {'file_path': 'tracked.txt', 'content': 'COMMITTED_TIP'})
    tip = bash(emulator, session, 'git add tracked.txt && ' + commit_template + 'tip && git rev-parse HEAD')
    assert re.fullmatch('[a-f0-9]{40}', tip) and tip != base, tip
    agent['tool'](emulator, session, 'write', {'file_path': 'uncommitted.txt', 'content': 'UNCOMMITTED'})
    evidence['committedTip'] = tip

    emulator.app(f'rm -rf {checkout}')
    emulator.rpc('forgePanel/restoreWorktree', {'sessionId': session})
    assert agent['read_bytes'](emulator, checkout + '/tracked.txt') == b'COMMITTED_TIP'
    assert emulator.app(f'test ! -e {checkout}/uncommitted.txt && printf ABSENT') == 'ABSENT'
    assert bash(emulator, session, 'git rev-parse HEAD') == tip
    assert agent['read_bytes'](emulator, folder + '/tracked.txt') == b'BASE'
    evidence['existingBranchRestoredAtCommittedTip'] = True
    print('Restored the existing branch at its committed tip', flush=True)

    emulator.app(f'rm -rf {checkout}; touch {folder}/hold-reset')
    cancel_restore(emulator, session, folder, evidence)
    assert emulator.app(f'test -f {checkout}/.git && test ! -e {checkout}/tracked.txt && printf PARTIAL') == 'PARTIAL'
    assert agent['read_bytes'](emulator, folder + '/.git/refs/heads/' + branch).decode().strip() == tip
    evidence['cancelPreservedBranchAndReportedPartialCheckout'] = True

    # Upstream intentionally retains partial artifacts after cancellation. Drop
    # only this fixture's directory and branch to cover the missing-branch path.
    emulator.app(f'rm -rf {checkout}; rm -f {folder}/hold-reset {folder}/.git/refs/heads/{branch}')
    assert emulator.app(f'test ! -e {folder}/.git/refs/heads/{branch} && printf ABSENT') == 'ABSENT'
    emulator.rpc('forgePanel/restoreWorktree', {'sessionId': session})
    assert agent['read_bytes'](emulator, checkout + '/tracked.txt') == b'BASE'
    assert bash(emulator, session, 'git rev-parse HEAD') == base
    evidence['missingBranchRecreatedAtBaseAfterCancellation'] = True
    evidence['forgeActions'] = forge_actions(emulator, session)
    assert evidence['forgeActions'] == [
        'request', 'restoring', 'restored', 'restoring', 'restoring', 'restored',
    ], evidence
    sessions.remove(session)
    emulator.stop()
    emulator.start()
    evidence['restartReadyMs'] = emulator.ready('normal')
    sessions.append(session)
    result, _ = agent['tool'](emulator, session, 'working_directory', {})
    assert toolkit['texts']([result]).strip() == created['path']
    assert agent['read_bytes'](emulator, checkout + '/tracked.txt') == b'BASE'
    evidence['restoredSessionRetainedAcrossRestart'] = True
    sessions.remove(session)
    print('Verified cancellation, recreation at base, and restart', flush=True)


def catalog_state(emulator, enabled):
    catalog = emulator.rpc('pluginManager/listBundles', {})
    rows = {}
    for name in CATALOG:
        row, = [row for row in catalog if row['name'] == name]
        assert row['availability'] == 'installation' and row['optional'] and row['official'], row
        assert not row['installed'] and not row['removable'] and not row.get('error'), row
        assert row['version'] == '0.2.2-rc.4' and row['enabled'] == (name in enabled), row
        keys = ['availability', 'optional', 'official', 'installed', 'removable', 'version', 'enabled']
        rows[name] = {key: row[key] for key in keys}
    return rows


def enable_from_catalog(emulator):
    enabled = set()
    evidence = {'default': catalog_state(emulator, enabled), 'switches': []}
    for name, module in CATALOG.items():
        for value in ([True] if name == FORGE else [True, False]):
            change = emulator.rpc('pluginManager/setBundleEnabled', {'name': name, 'enabled': value})
            assert change['application'] in ['applied', 'restart-required'], change
            (enabled.add if value else enabled.remove)(name)
            emulator.stop()
            emulator.start()
            ready = emulator.ready('normal')
            catalog_state(emulator, enabled)
            active = any(row['moduleName'] == module and row.get('enabled') and row.get('fiberPhase') == 'active'
                         for row in emulator.rpc('pluginManager/listPlugins', {}))
            assert active == value, (name, module, active, change)
            evidence['switches'].append({'bundle': name, 'enabled': value, 'module': module,
                                         'moduleActive': active, 'readyMs': ready, 'application': change['application']})
    print('Verified official installation catalog and persisted selections', flush=True)
    return evidence


def run(emulator, output, use_catalog):
    name = 'mh-worktree-restore-' + uuid.uuid4().hex[:10]
    repo = support['WORKSPACE'] + '/' + name
    folder = 'alpine/workspace-native/' + name
    remote = '/data/local/tmp/' + name
    originals = {}
    evidence = {'fixture': name}
    try:
        emulator.ready('normal')
        assert emulator.app('test ! -e ' + PATCH + ' && printf EMPTY') == 'EMPTY'
        original_paths = [PROFILE + '/package.json', PROFILE + '/pnpm-lock.yaml', 'mobile-harness-boot.json']
        originals = {file: agent['read_bytes'](emulator, file) for file in original_paths}
        manifest = json.loads(originals[original_paths[0]])
        bundles = manifest['dsh']['profile']['bundles']
        assert FORGE not in bundles and '@deepseek-ai/dsh-experimental-tool-worktree' not in bundles
        source = Path(__file__).with_name('fixtures').joinpath('worktree-restore-gate.mjs').read_text()
        source = source.replace('__MH_REPOSITORY__', json.dumps(repo))
        source = source.replace('__MH_GUEST_BASH__', json.dumps(support['WORKSPACE'].rsplit('/', 1)[0] + '/bin/bash'))
        patch = f'- insert:\n    - id: {name}\n      name: "file://{repo}/restore-gate.mjs"\n'
        emulator.stop()
        emulator.app(f'mkdir {folder}')
        lsp['restore_bytes'](emulator, folder + '/restore-gate.mjs', source.encode(), remote + '-module')
        lsp['restore_bytes'](emulator, PATCH, patch.encode(), remote + '-patch')
        if not use_catalog:
            bundles.append(FORGE)
            lsp['restore_bytes'](emulator, original_paths[0], json.dumps(manifest).encode(), remote + '-profile')
        emulator.start()
        evidence['forgeReadyMs'] = emulator.ready('normal')
        if use_catalog:
            evidence['catalog'] = enable_from_catalog(emulator)
            assert agent['read_bytes'](emulator, original_paths[1]) == originals[original_paths[1]]
            evidence['catalogTogglesDidNotChangeLock'] = True
        sessions = []
        with support['model_key'](emulator):
            try:
                check_restore(emulator, folder, repo, evidence, sessions)
            except Exception:
                for session in sessions:
                    try:
                        emulator.rpc('session/cancel', {'request': {'sessionId': session}})
                    except RuntimeError as error:
                        evidence.setdefault('failureCleanupErrors', []).append(str(error))
                raise
        evidence['testCredentialRemoved'] = True
    finally:
        try:
            if originals:
                emulator.stop()
                emulator.app(f'rm -f {PATCH}; rm -rf {folder}')
                for index, (file, body) in enumerate(originals.items()):
                    lsp['restore_bytes'](emulator, file, body, remote + '-restore-' + str(index))
                emulator.start()
                evidence['restoredReadyMs'] = emulator.ready('normal')
                after = {file: agent['read_bytes'](emulator, file) for file in originals}
                assert after == originals
                evidence['originalConfigurationHashes'] = {file: hashlib.sha256(body).hexdigest() for file, body in after.items()}
                assert emulator.app(f'test ! -e {PATCH} && test ! -e {folder} && printf ABSENT') == 'ABSENT'
                evidence['fixtureRemoved'] = True
        finally:
            output.write_text(json.dumps(evidence, indent=2) + '\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('target')
    parser.add_argument('output', type=Path)
    parser.add_argument('--catalog', action='store_true', help='Enable bundles using the 0.4.37 installation catalog')
    options = parser.parse_args()
    if not os.environ.get('MH_TEST_DEEPSEEK_API_KEY'):
        parser.error('MH_TEST_DEEPSEEK_API_KEY is required')
    emulator = support['Emulator'](options.target, 19643)
    forward = ('tcp:19643', 'tcp:19592')
    emulator.hdc('fport', *forward)
    try:
        run(emulator, options.output, options.catalog)
    finally:
        emulator.hdc('fport', 'rm', *forward)
