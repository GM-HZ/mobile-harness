"""Actual model-facing Host and live ArkWeb Client Cordis inspection."""
import argparse
import hashlib
import json
import os
import re
from pathlib import Path
import runpy
import time

agent = runpy.run_path(str(Path(__file__).with_name('emulator-agent-continuation.py')))
support = agent['support']; toolkit = agent['toolkit']


def invoke(emulator, sid, evidence, key, platform, provider, method, input=None, error=False):
    args = {'platform': platform, 'provider': provider, 'method': method}
    if input is not None: args['input'] = input
    started = time.monotonic()
    result, _ = agent['tool'](emulator, sid, 'cordis_inspect_query', args, expect_error=error)
    text = toolkit['texts']([result])
    offload = None
    if error:
        value = text
    else:
        try: value = json.loads(text)
        except json.JSONDecodeError:
            # Large directories use the normal tool-output retention contract.
            # Verify its complete stored JSON and make the real Agent read its
            # first page; never mistake clipped inline text for malformed data.
            match = re.search(r'Full formatted result stored at: (/.+?\.txt)\.', text)
            if match is None: raise
            path = match[1]; root = support['WORKSPACE'].rsplit('/', 1)[0]
            assert path.startswith(root + '/tmp/dsh-spill-') and path.endswith('-cordis_inspect_query.txt'), path
            body = agent['read_bytes'](emulator, 'alpine/' + path[len(root) + 1:])
            value = json.loads(body)
            page, _ = agent['tool'](emulator, sid, 'read', {'file_path': path, 'offset': 1, 'limit': 80})
            page_text = toolkit['texts']([page]); assert 'platform' in page_text and 'provider' in page_text
            offload = {'path': path, 'bytes': len(body), 'sha256': hashlib.sha256(body).hexdigest(),
                       'actualAgentReadFirstPage': page_text}
    evidence[key] = {'args': args, 'result': value, 'elapsedMs': round((time.monotonic() - started) * 1000)}
    if offload is not None: evidence[key]['offloadedFullResult'] = offload
    print(key, 'rejected' if error else 'returned', flush=True)
    if not error:
        assert value['platform'] == platform and value['provider'] == provider and value['method'] == method
        return value['data']
    return value


def providers(emulator, sid, evidence, key):
    attempts = []; deadline = time.monotonic() + 40
    while time.monotonic() < deadline:
        result, _ = agent['tool'](emulator, sid, 'cordis_inspect_list', {})
        data = json.loads(toolkit['texts']([result])); attempts.append(data)
        listed = {(row['platform'], row['id']) for row in data['providers']}
        if {('host', p) for p in ['Service', 'Event', 'Config', 'Tool']} <= listed and {('client', p) for p in ['Service', 'Event', 'Builtin', 'Slots', 'Theme']} <= listed:
            evidence[key] = attempts; return data
    evidence[key] = attempts
    raise AssertionError('Real ArkWeb Client inspection manifests did not arrive')


def run(emulator, output):
    evidence = {}; sid = None; unfinished = False
    profile = 'alpine/native-benchmark-home/profiles/web/'
    original = {file: hashlib.sha256(agent['read_bytes'](emulator, profile + file)).hexdigest() for file in ['package.json', 'pnpm-lock.yaml']}
    try:
        emulator.ready('normal')
        with support['model_key'](emulator):
            workspace = emulator.rpc('workspace/create', {'request': {'path': support['WORKSPACE']}})['workspace']
            sid = emulator.rpc('session/create', {'request': {'workspaceId': workspace['workspaceId'], 'agentPreset': 'cordis'}})['sessionId']
            evidence['sessionId'] = sid
            emulator.rpc('session/selectModel', {'request': {'sessionId': sid, 'provider': 'deepseek-official', 'model': 'deepseek-flash', 'reasoningEffort': 'off'}})
            unfinished = True
            directory = providers(emulator, sid, evidence, 'providerLists')
            host = {p['id']: p for p in directory['providers'] if p['platform'] == 'host'}
            client = {p['id']: p for p in directory['providers'] if p['platform'] == 'client'}
            assert host['Service']['methods'][0]['name'] == 'listService'
            service = invoke(emulator, sid, evidence, 'hostSubprocessContract', 'host', 'Service', 'listService', {'service': 'subprocess'})
            assert service['mode'] == 'service' and service['service']['key'] == 'subprocess'
            assert all(name in json.dumps(service) for name in ['spawn', 'resolveExecutable', 'SubprocessSpawnSpec'])
            event = invoke(emulator, sid, evidence, 'hostStreamContract', 'host', 'Event', 'listEvents', {'event': 'llm/stream'})
            assert event['event']['name'] == 'llm/stream' and event['event']['mode'] == 'waterfall'
            first = invoke(emulator, sid, evidence, 'configFirstPage', 'host', 'Config', 'listConfigs', {'offset': 0, 'limit': 2})
            second = invoke(emulator, sid, evidence, 'configSecondPage', 'host', 'Config', 'listConfigs', {'offset': first['nextOffset'], 'limit': 2})
            assert len(first['entries']) == len(second['entries']) == 2 and first['total'] == second['total']
            assert {v['id'] for v in first['entries']}.isdisjoint({v['id'] for v in second['entries']})
            listing = invoke(emulator, sid, evidence, 'liveLspConfigEntry', 'host', 'Config', 'listConfigs', {'name': '@deepseek-ai/dsh-lsp-stdio'})
            assert listing['total'] == 1 and listing['entries'][0]['status'] == 'schema', listing
            entry = listing['entries'][0]['id']
            schema = invoke(emulator, sid, evidence, 'liveLspConfigSchema', 'host', 'Config', 'listConfigs', {'entry': entry})
            assert schema['id'] == entry and schema['schema']['$schema'].endswith('2020-12/schema')
            assert 'servers' in json.dumps(schema['schema']) and 'shutdownTimeoutMs' in json.dumps(schema['schema'])
            tools = invoke(emulator, sid, evidence, 'effectiveAgentTools', 'host', 'Tool', 'listTools', {})
            assert {'cordis_inspect_list', 'cordis_inspect_query', 'write'} <= {tool['name'] for tool in tools['tools']}
            invalid = invoke(emulator, sid, evidence, 'businessMethodRefused', 'host', 'Service', 'write', {'service': 'fs'}, True)
            assert 'method' in invalid.lower() and 'write' in invalid
            invalid = invoke(emulator, sid, evidence, 'invalidInputRefused', 'host', 'Service', 'listService', {'unexpected': True}, True)
            assert 'input' in invalid.lower()
            assert client['Theme']['methods'][0]['name'] == 'listTokens'
            themes = invoke(emulator, sid, evidence, 'actualClientThemeTokens', 'client', 'Theme', 'listTokens', {})
            assert themes['tokens'], themes
            builtins = invoke(emulator, sid, evidence, 'actualClientBuiltins', 'client', 'Builtin', 'listBuiltins', {})
            assert builtins['builtins'] and 'React' in json.dumps(builtins)
            services = invoke(emulator, sid, evidence, 'actualClientServiceCatalog', 'client', 'Service', 'listService', {})
            assert services['mode'] == 'catalog' and services['services']
            assert any(row['key'] == 'slots' for row in services['services'])
            events = invoke(emulator, sid, evidence, 'actualClientEventCatalog', 'client', 'Event', 'listEvents', {})
            assert events['mode'] == 'catalog' and events['events']
            slots = invoke(emulator, sid, evidence, 'actualClientSlots', 'client', 'Slots', 'listSubTree', {})
            assert slots['trees'], slots
            root = slots['trees'][0]
            selected_root = ('factory:' if root['type'] == 'factory' else '') + root['name']
            detail = invoke(emulator, sid, evidence, 'actualClientSlotDetail', 'client', 'Slots', 'listSubTree', {'root': selected_root})
            assert detail['requestedRoot']['available'] is True and detail['selected']['name'] == root['name']
            unfinished = False
            emulator.stop(); emulator.start(); evidence['restartReadyMs'] = emulator.ready('normal')
            unfinished = True
            providers(emulator, sid, evidence, 'providerListsAfterRestart')
            after = invoke(emulator, sid, evidence, 'actualClientAfterRestart', 'client', 'Builtin', 'listBuiltins', {})
            assert after == builtins
            unfinished = False; evidence['sameCordisSessionAndRealClientAfterRestart'] = True
        evidence['temporaryModelCredentialRemoved'] = True
    finally:
        try:
            if sid and unfinished: emulator.rpc('session/cancel', {'request': {'sessionId': sid}})
            after = {file: hashlib.sha256(agent['read_bytes'](emulator, profile + file)).hexdigest() for file in original}
            assert original == after, (original, after)
            evidence['configurationHashesUnchanged'] = after
        finally: output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + '\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('target'); parser.add_argument('output', type=Path); options = parser.parse_args()
    if not os.environ.get('MH_TEST_DEEPSEEK_API_KEY'): parser.error('MH_TEST_DEEPSEEK_API_KEY is required')
    emulator = support['Emulator'](options.target, 19643); forward = ('tcp:19643', 'tcp:19592')
    emulator.hdc('fport', *forward)
    try: run(emulator, options.output)
    finally: emulator.hdc('fport', 'rm', *forward)
