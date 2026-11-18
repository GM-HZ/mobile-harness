"""Verify live OpenAI-compatible routes configured through the standard DSH settings API."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import runpy
import uuid

agent = runpy.run_path(str(Path(__file__).with_name('emulator-agent-continuation.py')))
support = agent['support']
lsp = runpy.run_path(str(Path(__file__).with_name('emulator-lsp-lifecycle.py')))
NS = 'llm-pi-ai'
MODEL = 'deepseek-flash'
REF = 'MH_SMOKE_PI_AI_KEY'
BASE_URL = 'https://api.deepseek.com'
APIS = ('openai-completions', 'openai-responses')
PROFILE = 'alpine/native-benchmark-home/profiles/web'


def settings(device):
    return next(row for row in device.rpc('settings/describe', {})['namespaces'] if row['ns'] == NS)


def profiles(name):
    return {
        name + '-' + api: {
            'displayName': 'Mobile Harness ' + api,
            'api': api,
            'baseURL': BASE_URL,
            'apiKeyEnv': REF,
            'compat': {'thinkingFormat': 'deepseek'} if api == 'openai-completions' else {},
            'models': [{'id': MODEL, 'contextWindow': 1_048_576, 'maxTokens': 2048,
                        'reasoningEfforts': {'off': None, 'high': 'high'}}],
        }
        for api in APIS
    }


def digest_launch(device):
    return hashlib.sha256(agent['read_bytes'](device, 'alpine/tmp/dsh-client-native-launch')).digest()


def verify_route(device, workspace, path, api, route, marker, register_session):
    listed = device.rpc('llm/discoverModels', {'settingsNs': NS, 'request': {
        'provider': route, 'api': api, 'baseURL': BASE_URL,
    }}, timeout=45)
    discovered, = [row for row in listed if row['id'] == MODEL]
    session = device.rpc('session/create', {'request': {'workspaceId': workspace}})['sessionId']
    register_session.append(session)
    device.rpc('session/selectModel', {'request': {'sessionId': session, 'provider': route,
               'model': MODEL, 'reasoningEffort': 'off'}})
    calls, results, rows = agent['prompt'](device, session,
        'Call the read tool exactly once with ' + json.dumps({'file_path': path})
        + '. Then reply with exactly the token from the file. Use no other tools.', timeout=65)
    assert [row['name'] for row in calls] == ['read']
    assert json.loads(calls[0]['arguments']) == {'file_path': path}
    assert marker in agent['toolkit']['texts'](results)
    messages = [row['data']['message'] for row in rows if row['type'] == 'assistant/message']
    assert len(messages) >= 2
    assert all(row['source']['provider'] == route and row['source']['model'] == MODEL for row in messages)
    tail = ''.join(block.get('text', '') for block in messages[-1]['content']).strip()
    assert tail == marker, 'The model did not repeat the tool result'
    return {'session': session, 'modelDiscovery': discovered, 'exactToolRoundTrip': True,
            'durableRoute': route}


def run(device, output):
    name = 'mh-pi-' + uuid.uuid4().hex[:10]
    marker = 'PI_ROUTE_' + uuid.uuid4().hex.upper()
    folder = 'alpine/workspace-native/' + name
    path = support['WORKSPACE'] + '/' + name
    bridge = ('tcp:19643', 'tcp:19592')
    evidence = {'protocols': {}}
    originals = {}
    temporary_key = False
    workspace = None
    sessions = []
    assert 'Forwardport result:OK' in device.hdc('fport', *bridge)
    try:
        device.ready('normal')
        original = settings(device)
        files = [PROFILE + '/' + leaf for leaf in ('package.json', 'pnpm-lock.yaml', 'cordis.patch.yml')]
        originals = {file: agent['read_bytes'](device, file) for file in files + ['mobile-harness-boot.json']}
        launch = digest_launch(device)
        assert not device.rpc('credentials/describe', {'refs': [REF]})[REF]['configured']
        device.rpc('credentials/set', {'ref': REF, 'value': os.environ['MH_TEST_DEEPSEEK_API_KEY']})
        temporary_key = True
        state = {**original['user'], 'providers': {**original['user'].get('providers', {}), **profiles(name)}}
        device.rpc('settings/replace', {'ns': NS, 'section': state, 'expectedRevision': original['revision']})
        assert settings(device)['user'] == state
        device.app(f'mkdir {folder} && printf %s {marker} > {folder}/answer.txt')
        workspace = device.rpc('workspace/create', {'request': {'path': path}})['workspace']['workspaceId']
        for api in APIS:
            route = name + '-' + api
            evidence['protocols'][api] = verify_route(device, workspace, path + '/answer.txt', api, route, marker, sessions)
        assert digest_launch(device) == launch
        evidence['registeredAndUsedWithoutRestart'] = True
        device.stop()
        device.start()
        evidence['restartReadyMs'] = device.ready('normal')
        assert settings(device)['user'] == state
        for result in evidence['protocols'].values():
            session = result['session']
            before = support['events'](device, session)
            boundary = before[-1]['seq']
            calls, _, after = agent['prompt'](device, session,
                'Repeat only the exact value we read earlier. No tools or other text.', timeout=65)
            assert not calls
            assert agent['assistant_texts']([row for row in after if row['seq'] > boundary]).strip() == marker
            result['recallAfterRestart'] = True
    finally:
        try:
            for session in sessions:
                device.rpc('workspace/archiveSession', {'request': {'sessionId': session}})
            if workspace:
                assert device.rpc('workspace/delete', {'request': {'workspaceId': workspace}}) == {'deleted': True}
        finally:
            try:
                if temporary_key:
                    device.rpc('credentials/unset', {'ref': REF})
                    assert not device.rpc('credentials/describe', {'refs': [REF]})[REF]['configured']
                    evidence['testCredentialRemoved'] = True
                if originals:
                    device.stop()
                    device.app('rm -rf ' + folder)
                    for index, (file, body) in enumerate(originals.items()):
                        lsp['restore_bytes'](device, file, body, '/data/local/tmp/' + name + str(index))
                    device.start()
                    device.ready('normal')
                    assert all(agent['read_bytes'](device, file) == body for file, body in originals.items())
                    evidence['profileRestored'] = True
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
