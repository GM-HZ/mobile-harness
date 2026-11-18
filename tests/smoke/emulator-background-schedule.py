"""Keep the simulator in Home while three scheduled turns run on the real DSH Host."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import runpy
import time
import uuid

agent = runpy.run_path(str(Path(__file__).with_name('emulator-agent-continuation.py')))
support = agent['support']
LAUNCH = 'alpine/tmp/dsh-client-native-launch'
DELAYS = (16, 48, 80)


def page_state(device):
    lines = device.hdc('shell', 'aa', 'dump', '-a')
    block = lines.split('app name [org.sayact.nodepoc]', 1)[-1]
    match = re.search(r'main name \[EntryAbility\]\s+bundle name \[org\.sayact\.nodepoc\]\s+'
                      r'ability type \[PAGE\]\s+state #([A-Z]+)', block)
    return match.group(1) if match else None


def wait_page(device, expected):
    deadline = time.monotonic() + 12
    while time.monotonic() < deadline:
        if page_state(device) == expected:
            return
        time.sleep(.2)
    raise AssertionError('System did not report ' + expected)


def schedule_result(device, session, task, rows):
    view = device.rpc('schedule/view', {'request': {'id': task['id']}})
    delivery = view.get('lastDelivery')
    if not delivery:
        return None
    assert delivery['targetSessionId'] == session, delivery
    prompts = [row for row in rows if row['type'] == 'user/message'
               and row['data']['source']['kind'] == 'schedule'
               and task['marker'] in json.dumps(row['data']['content'])]
    if not prompts:
        return None
    assert len(prompts) == 1
    starts = [row for row in rows if row['type'] == 'turn/start' and row['seq'] < prompts[0]['seq']]
    turn = starts[-1]['data']['turn']
    end = [row for row in rows if row['type'] == 'turn/end' and row['data']['turn'] == turn]
    if not end:
        return None
    events = [row for row in rows if starts[-1]['seq'] <= row['seq'] <= end[0]['seq']]
    assert end[0]['data']['reason']['kind'] == 'completed'
    assert agent['assistant_texts'](events).strip() == task['marker']
    assert not any(row['type'] == 'tool/call' for row in events)
    return {'afterSeconds': task['delay'], 'finishedTurn': turn,
            'exactReply': True, 'source': 'schedule', 'receipt': delivery}


def run(device, output):
    name = 'mh-background-' + uuid.uuid4().hex[:10]
    folder = 'alpine/workspace-native/' + name
    path = support['WORKSPACE'] + '/' + name
    marker = 'DURABLE_' + uuid.uuid4().hex.upper()
    workspace = None
    session = None
    backgrounded = False
    tasks = []
    evidence = {'deliveries': []}
    bridge = ('tcp:19643', 'tcp:19592')
    assert 'Forwardport result:OK' in device.hdc('fport', *bridge)
    try:
        device.start()
        device.ready('normal')
        wait_page(device, 'FOREGROUND')
        device.app('mkdir ' + folder)
        workspace = device.rpc('workspace/create', {'request': {'path': path}})['workspace']['workspaceId']
        with support['model_key'](device):
            session = device.rpc('session/create', {'request': {'workspaceId': workspace}})['sessionId']
            device.rpc('session/selectModel', {'request': {'sessionId': session, 'provider': 'deepseek-official',
                       'model': 'deepseek-flash', 'reasoningEffort': 'off'}})
            calls, _, _ = agent['prompt'](device, session,
                'Remember the exact background acceptance label ' + marker
                + '. Acknowledge briefly and take no other action. Do not write files or call tools.')
            assert not calls
            launch = hashlib.sha256(agent['read_bytes'](device, LAUNCH)).digest()
            prior = support['events'](device, session)
            for index, delay in enumerate(DELAYS, 1):
                reply = f'SCHEDULED_{index}_' + uuid.uuid4().hex.upper()
                task = device.rpc('schedule/create', {'request': {
                    'title': name + '-' + str(index),
                    'prompt': 'Reply only with the exact text ' + reply + '. Do not call tools.',
                    'timing': {'kind': 'after', 'after_seconds': delay},
                    'target': {'kind': 'session', 'sessionId': session},
                }})
                tasks.append({'id': task['id'], 'marker': reply, 'delay': delay})
            backgrounded = True
            device.hdc('shell', 'uitest', 'uiInput', 'keyEvent', 'Home')
            wait_page(device, 'BACKGROUND')
            started = time.monotonic()
            pending = list(tasks)
            samples = 0
            observed = []
            while pending and time.monotonic() - started < 108:
                assert page_state(device) == 'BACKGROUND'
                samples += 1
                observed = support['events'](device, session)
                for task in pending[:]:
                    result = schedule_result(device, session, task, observed)
                    if result:
                        result['observedAtMs'] = round((time.monotonic() - started) * 1000)
                        evidence['deliveries'].append(result)
                        pending.remove(task)
                if pending:
                    time.sleep(1.5)
            assert not pending, f'Missing schedules after delays {[task["delay"] for task in pending]}'
            assert hashlib.sha256(agent['read_bytes'](device, LAUNCH)).digest() == launch
            evidence['backgroundDurationMs'] = round((time.monotonic() - started) * 1000)
            evidence['backgroundStateSamples'] = samples
            evidence['hostLaunchIdentityUnchanged'] = True
            evidence['journalPreservedWhileBackgrounded'] = observed[:len(prior)] == prior
            assert evidence['journalPreservedWhileBackgrounded']
            device.start()
            wait_page(device, 'FOREGROUND')
            backgrounded = False
            assert hashlib.sha256(agent['read_bytes'](device, LAUNCH)).digest() == launch
            cutoff = observed[-1]['seq']
            calls, _, rows = agent['prompt'](device, session,
                'Return the original background acceptance label from the first turn exactly, with no tools or other text.')
            assert not calls
            assert agent['assistant_texts']([row for row in rows if row['seq'] > cutoff]).strip() == marker
            assert rows[:len(observed)] == observed
            evidence['foregroundExactRecall'] = True
        evidence['testCredentialRemoved'] = True
    finally:
        try:
            if backgrounded:
                device.start()
                wait_page(device, 'FOREGROUND')
            for task in tasks:
                deleted = device.rpc('schedule/edit', {'request': {'id': task['id'], 'action': 'delete'}})
                assert deleted.get('deleted') is True, deleted
            if session:
                device.rpc('workspace/archiveSession', {'request': {'sessionId': session}})
            if workspace:
                assert device.rpc('workspace/delete', {'request': {'workspaceId': workspace}}) == {'deleted': True}
            device.app('rm -rf ' + folder)
        finally:
            device.hdc('fport', 'rm', *bridge)
            output.write_text(json.dumps(evidence, indent=2) + '\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('target')
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    if not os.environ.get('MH_TEST_DEEPSEEK_API_KEY'):
        parser.error('MH_TEST_DEEPSEEK_API_KEY is required')
    run(support['Emulator'](args.target, 19643), args.output)
