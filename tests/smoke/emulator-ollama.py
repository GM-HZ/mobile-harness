"""Exercise a real local Ollama model through the normal DSH provider settings."""
import argparse
import hashlib
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import runpy
import threading
import time
import uuid

pi = runpy.run_path(str(Path(__file__).with_name('emulator-pi-ai-protocols.py')))
market = runpy.run_path(str(Path(__file__).with_name('emulator-plugin-market.py')))
vision = runpy.run_path(str(Path(__file__).with_name('emulator-deepseek-vision.py')))
agent, support = pi['agent'], pi['support']
NS = pi['NS']
PROFILE = pi['PROFILE']
REF = 'MH_SMOKE_OLLAMA_PLACEHOLDER'
KEY = 'ollama-local-smoke'
DEVICE_PORT = 19776
BASE = f'http://127.0.0.1:{DEVICE_PORT}/v1'
ENDPOINTS = {'openai-completions': '/v1/chat/completions', 'openai-responses': '/v1/responses'}


def request_traits(value):
    kinds = set()
    def collect(item):
        if isinstance(item, dict):
            if isinstance(item.get('role'), str):
                kinds.add(item['role'])
            if isinstance(item.get('type'), str):
                kinds.add(item['type'])
            for child in item.values():
                collect(child)
        elif isinstance(item, list):
            for child in item:
                collect(child)
    collect(value.get('input', value.get('messages', [])))
    return {'hasTools': bool(value.get('tools')), 'hasToolResult': bool(kinds & {'tool', 'function_call_output'}),
            'hasImage': bool(kinds & {'image_url', 'input_image'}), 'stream': value.get('stream', False)}


class OllamaFixture(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_GET(self):
        if self.path != '/v1/models':
            self.send_error(404)
            return
        self.forward(None, {})

    def do_POST(self):
        if self.path not in ENDPOINTS.values():
            self.send_error(404)
            return
        if self.headers.get('Authorization') != 'Bearer '+KEY:
            self.send_error(403)
            return
        length = int(self.headers.get('Content-Length', '0'))
        if not 0 < length <= 2 * 1024 * 1024:
            self.send_error(413)
            return
        body = self.rfile.read(length)
        request = json.loads(body)
        if request.get('model') != self.server.model:
            self.send_error(400, 'Fixture accepts only its configured local model')
            return
        self.forward(body, request_traits(request))

    def forward(self, body, traits):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.ollama_port, timeout=90)
        start = time.monotonic()
        evidence = {'method': self.command, 'path': self.path, **traits}
        try:
            connection.request(self.command, self.path, body=body, headers={'Content-Type': 'application/json'})
            response = connection.getresponse()
            evidence['status'] = response.status
            evidence['responseType'] = response.getheader('Content-Type', '')
            self.send_response(response.status)
            self.send_header('Content-Type', evidence['responseType'])
            self.end_headers()
            error = bytearray()
            while data := response.read1(16384):
                if response.status >= 400 and len(error) < 768:
                    error.extend(data[:768-len(error)])
                self.wfile.write(data)
                self.wfile.flush()
            if error:
                evidence['error'] = error.decode(errors='replace')
        except (BrokenPipeError, ConnectionResetError):
            evidence['callerDisconnected'] = True
        finally:
            evidence['elapsedMs'] = round((time.monotonic()-start)*1000)
            self.server.calls.append(evidence)
            connection.close()


def provider_profile(api, model, context_window, max_tokens):
    compat = {'supportsDeveloperRole': False}
    if api == 'openai-completions':
        compat.update(maxTokensField='max_tokens', supportsReasoningEffort=False, supportsStore=False)
    return {'displayName': 'Ollama smoke '+api, 'api': api, 'baseURL': BASE,
            'apiKeyEnv': REF, 'compat': compat, 'models': [
                {'id': model, 'input': ['text', 'image'], 'contextWindow': context_window, 'maxTokens': max_tokens,
                 'reasoningEfforts': False},
            ]}


def turn_outcome(device, session, instruction, timeout=140):
    """Run one addressed turn and return its end reason, tool calls and rows.

    A small local model may stop on max-tokens instead of completing; the
    provider contract still holds as long as the turn ends with an assistant
    message attributed to the configured route. Model quality is therefore
    reported, not asserted away.
    """
    text = 'ACCEPTANCE' + uuid.uuid4().hex.upper() + ': ' + instruction
    device.rpc('session/prompt', {'request': {
        'sessionId': session, 'requestId': str(uuid.uuid4()), 'mode': 'queue',
        'content': [{'type': 'text', 'text': text}],
    }})
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        rows = support['events'](device, session)
        anchor = next((row for row in rows if row['type'] == 'user/message' and
                       any(item.get('text') == text for item in row['data'].get('content', []))), None)
        if anchor:
            starts = [row for row in rows if row['type'] == 'turn/start' and row['seq'] < anchor['seq']]
            assert starts, anchor
            turn = starts[-1]['data']['turn']
            ended = next((row for row in rows if row['type'] == 'turn/end' and row['data']['turn'] == turn), None)
            if ended:
                calls = [row['data'] for row in rows if row['type'] == 'tool/call' and row['data']['turn'] == turn]
                ids = {call['callId'] for call in calls}
                results = [row['data']['message'] for row in rows if row['type'] == 'tool/result'
                           and row['data']['message'].get('toolCallId') in ids]
                return {'end': ended['data']['reason']['kind'], 'turn': turn, 'calls': calls,
                        'results': results, 'rows': rows}
        time.sleep(.1)
    raise AssertionError('The addressed Ollama turn did not finish')


def route_messages(outcome, route, model):
    turn = outcome['turn']
    messages = [row['data']['message'] for row in outcome['rows']
                if row['type'] == 'assistant/message' and row['data']['turn'] == turn]
    assert messages, outcome['rows']
    assert all(row['source']['provider'] == route and row['source']['model'] == model for row in messages)
    return messages


def verify_route(device, workspace, api, route, model, token, sessions):
    discovered = device.rpc('llm/discoverModels', {'settingsNs': NS, 'request': {
        'provider': route, 'api': api, 'baseURL': BASE,
    }}, timeout=30)
    assert any(row['id'] == model for row in discovered), discovered
    session = device.rpc('session/create', {'request': {'workspaceId': workspace}})['sessionId']
    sessions.append(session)
    device.rpc('session/selectModel', {'request': {'sessionId': session, 'provider': route,
               'model': model}})
    tool_turn = turn_outcome(device, session,
        'Use the read tool exactly once with file_path set to answer.txt. '
        'Then repeat the number read from the file. Do not guess and do not use other tools.')
    tool_names = [call['name'] for call in tool_turn['calls']]
    tool_round_trip = tool_names == ['read'] and json.loads(tool_turn['calls'][0]['arguments']) == {'file_path': 'answer.txt'}
    record = {'session': session, 'modelDiscovered': True, 'toolRoundTrip': tool_round_trip,
              'toolTurnEnd': tool_turn['end'], 'toolNames': tool_names}
    if tool_round_trip:
        assert token in agent['toolkit']['texts'](tool_turn['results']), tool_turn['results']
    # The provider contract itself: the route answers a plain turn in this protocol.
    plain_turn = turn_outcome(device, session, 'Reply with exactly the word READY and nothing else.')
    messages = route_messages(plain_turn, route, model)
    answer = ''.join(part.get('text', '') for part in messages[-1]['content']).strip()
    assert answer, plain_turn['rows']
    record.update({'plainTurnEnd': plain_turn['end'], 'modelReply': answer})
    return record


def verify_image(device, session, route, model):
    receipt = vision['upload'](device, session, 'owned-color-sample.png', vision['sample']('red', 'blue'))
    before = max(row['seq'] for row in support['events'](device, session))
    device.rpc('session/prompt', {'request': {'sessionId': session, 'requestId': str(uuid.uuid4()), 'mode': 'queue',
        'content': [{'type': 'file', 'receiptId': receipt['receiptId']},
                    {'type': 'text', 'text': 'In this new image, what color is on the left and what color is on the right? Answer in English.'}],
    }})
    deadline = time.monotonic()+120
    while time.monotonic()<deadline:
        rows = [row for row in support['events'](device, session) if row['seq']>before]
        end = next((row['data']['reason']['kind'] for row in rows if row['type']=='turn/end'), None)
        if end:
            assert not any(row['type']=='tool/call' for row in rows)
            assert all(row['data']['message']['source']['provider']==route for row in rows
                       if row['type']=='assistant/message')
            text = agent['assistant_texts'](rows).strip()
            colors = re.findall(r'\b(red|blue|green|yellow)\b', text.lower())
            return {'model':model, 'reply':text, 'colorsMatched': colors == ['red','blue'],
                    'turnEnd': end, 'attachmentId':receipt['image']['attachmentId']}
        time.sleep(.25)
    raise AssertionError('The actual Ollama vision turn did not finish')


def run(device, args):
    name = 'mh-ollama-'+uuid.uuid4().hex[:10]
    folder = 'alpine/workspace-native/'+name
    app_path = support['WORKSPACE']+'/'+name
    token = str(10000 + int(uuid.uuid4().hex[:4],16))
    bridge = (f'tcp:{args.host_port}', 'tcp:19592')
    evidence, originals = {'model':args.model, 'protocols':{}}, {}
    workspace = None
    sessions = []
    temporary_key = False
    server = None
    reverse = None
    assert 'Forwardport result:OK' in device.hdc('fport', *bridge)
    try:
        device.ready('normal')
        original = pi['settings'](device)
        files = [PROFILE+'/'+part for part in ('package.json','pnpm-lock.yaml','cordis.patch.yml')]+['mobile-harness-boot.json']
        originals = {path: market['profile_file'](device,path) for path in files}
        assert not device.rpc('credentials/describe', {'refs':[REF]})[REF]['configured']
        device.rpc('credentials/set', {'ref':REF,'value':KEY})
        temporary_key = True
        server = ThreadingHTTPServer(('127.0.0.1',0), OllamaFixture)
        server.model, server.ollama_port, server.calls = args.model, args.ollama_port, []
        threading.Thread(target=server.serve_forever,daemon=True).start()
        candidate = (f'tcp:{DEVICE_PORT}',f'tcp:{server.server_port}')
        assert 'Forwardport result:OK' in device.hdc('rport',*candidate)
        reverse = candidate
        routes = {api:name+'-'+api for api in ENDPOINTS}
        configured = {**original['user'], 'providers': {
            **original['user'].get('providers', {}),
            **{route:provider_profile(api,args.model,args.context_window,args.max_tokens) for api,route in routes.items()},
        }}
        initial = pi['digest_launch'](device)
        device.rpc('settings/replace', {'ns':NS,'section':configured,'expectedRevision':original['revision']})
        assert pi['settings'](device)['user']==configured
        device.app(f'mkdir {folder} && printf %s {token} > {folder}/answer.txt')
        workspace = device.rpc('workspace/create', {'request':{'path':app_path}})['workspace']['workspaceId']
        for api, route in routes.items():
            evidence['protocols'][api] = verify_route(device,workspace,api,route,args.model,token,sessions)
        evidence['vision'] = verify_image(device,sessions[0],routes['openai-completions'],args.model)
        assert pi['digest_launch'](device)==initial
        evidence['routesActivatedWithoutRestart'] = True
        device.stop()
        device.start()
        evidence['restartReadyMs'] = device.ready('normal')
        assert pi['settings'](device)['user']==configured
        for api, route in routes.items():
            session = evidence['protocols'][api]['session']
            recall = turn_outcome(device, session,
                'What was the exact number we read from answer.txt earlier? Reply from memory without tools.', timeout=120)
            assert not recall['calls'], recall['calls']
            messages = route_messages(recall, route, args.model)
            answer = ''.join(part.get('text', '') for part in messages[-1]['content']).strip()
            evidence['protocols'][api]['postRestartTurn'] = bool(answer)
            evidence['protocols'][api]['recalledAfterRestart'] = token in answer
            evidence['protocols'][api]['recallReply'] = answer
        tool_calls = [api for api, row in evidence['protocols'].items() if row['toolRoundTrip']]
        for path in ENDPOINTS.values():
            wire = [row for row in server.calls if row['path']==path]
            assert any(row['hasTools'] and row['stream'] and row['status']==200 for row in wire), wire
            if tool_calls:
                assert any(row['hasToolResult'] and row['status']==200 for row in wire), wire
        assert any(row.get('hasImage') and row['status']==200 for row in server.calls)
    finally:
        try:
            for session in sessions:
                device.rpc('session/cancel', {'request':{'sessionId':session}})
                device.rpc('workspace/archiveSession', {'request':{'sessionId':session}})
            if workspace:
                assert device.rpc('workspace/delete', {'request':{'workspaceId':workspace}})=={'deleted':True}
        finally:
            try:
                if temporary_key:
                    device.rpc('credentials/unset', {'ref':REF})
                    assert not device.rpc('credentials/describe', {'refs':[REF]})[REF]['configured']
                    evidence['placeholderRemoved']=True
                if originals:
                    device.stop()
                    device.app('rm -rf '+folder)
                    for i, (path, data) in enumerate(originals.items()):
                        if data is None:
                            device.app('rm -f '+path)
                        else:
                            pi['lsp']['restore_bytes'](device,path,data,f'/data/local/tmp/{name}-{i}')
                    device.start()
                    device.ready('normal')
                    assert all(market['profile_file'](device,path)==data for path,data in originals.items())
                    evidence['profileRestored']=True
            finally:
                if reverse:
                    device.hdc('fport','rm',*reverse)
                if server:
                    server.shutdown()
                    server.server_close()
                    evidence['actualOllamaRequests']=server.calls
                device.hdc('fport','rm',*bridge)
                args.output.write_text(json.dumps(evidence,indent=2,ensure_ascii=False)+'\n')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('target')
    parser.add_argument('output',type=Path)
    parser.add_argument('--model',required=True)
    parser.add_argument('--context-window',type=int,required=True)
    parser.add_argument('--max-tokens',type=int,default=4096)
    parser.add_argument('--ollama-port',type=int,default=11434)
    parser.add_argument('--host-port',type=int,default=19652)
    args=parser.parse_args()
    run(support['Emulator'](args.target,args.host_port),args)
