"""Exercise the real LiveShare gateway and owner RPCs with a loopback Relay stand-in."""
import argparse
import base64
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import runpy
import select
import subprocess
import time
import uuid
from urllib.error import HTTPError
from urllib.request import Request, urlopen

flow = runpy.run_path(str(Path(__file__).with_name('emulator-personalized-recommendations.py')))
support, agent, lsp = (flow[name] for name in ['support', 'agent', 'lsp'])
ws_module = runpy.run_path(str(Path(__file__).with_name('emulator-ptc-approval.py')))['ws_module']
NAME = '@deepseek-ai/dsh-experimental-liveshare'


def owner(device, method, request, timeout=25):
    return device.rpc('liveshareShares/'+method, {'request': request}, timeout=timeout)


def relay_call(port, share, payload, *, token='fixture-viewer', path='/__share/rpc'):
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = 'Bearer '+token
    request = Request(f'http://127.0.0.1:{port}{path}?shareId={share}',
                      data=json.dumps(payload).encode(), headers=headers)
    try:
        with urlopen(request, timeout=8) as response:
            return response.status, json.load(response)
    except HTTPError as error:
        return error.code, json.load(error)


def reader_rpc(port, share, method, args):
    body = {'type': 'client-request', 'rpcId': str(uuid.uuid4()), 'method': method, 'payload': {'args': args}}
    return relay_call(port, share, {'op': 'call', 'path': '/api/'+method, 'body': body})


def verify_viewer_turn(device, port, share, session, evidence):
    nonce = 'VIEWER_' + uuid.uuid4().hex.upper()
    text = 'Reply only with '+nonce+'. Use no tools.'
    request_id = str(uuid.uuid4())
    device.rpc('session/selectModel', {'request': {'sessionId': session, 'provider': 'deepseek-official',
        'model': 'deepseek-flash', 'reasoningEffort': 'off'}})
    status, body = reader_rpc(port, share, 'session/prompt', {'request': {
        'sessionId': session, 'requestId': request_id, 'mode': 'queue',
        'content': [{'type': 'text', 'text': text}],
    }})
    assert status == 200 and body['result']['ok'], (status, body)
    deadline = time.monotonic()+60
    while time.monotonic()<deadline:
        rows = support['events'](device, session)
        submitted = next((row for row in rows if row['type']=='user/message'
                          and row['data']['source'].get('rpcId')==request_id), None)
        if submitted:
            messages = [row for row in rows if row['seq']>submitted['seq']]
            ended = next((row['data']['reason']['kind'] for row in messages if row['type']=='turn/end'),None)
            if ended:
                assert ended=='completed'
                assert not any(row['type']=='tool/call' for row in messages)
                assert agent['assistant_texts'](messages).strip()==nonce
                principal = submitted['data']['source']['principal']
                assert principal=={'kind':'share-viewer','shareId':share,
                                   'actor':{'providerId':'fixture','tenantId':'local','subjectId':'reader'}},principal
                evidence['actualViewerModelTurn']={'principal':principal,'exactReply':True,'endReason':ended}
                return
        time.sleep(.2)
    raise AssertionError('The specific viewer prompt did not complete')


def verify_reader(device, port, share, shared, outside, evidence, model):
    status, body = relay_call(port, share, {'op': 'asset', 'path': ''}, token=None)
    assert status == 401 and body['error'] == 'viewer-login-required'
    status, body = relay_call(port, share, {'op': 'asset', 'path': ''})
    assert status == 200 and body['contentType'].startswith('text/html'), (status, body.keys())
    html = base64.b64decode(body['base64'], validate=True)
    assert b'<html' in html and b'rel="manifest"' not in html
    status, body = reader_rpc(port, share, 'session/list', {'_request': {}})
    assert status == 200 and body['result']['ok'], (status, body)
    visible = {row['sessionId'] for row in body['result']['value']['items']}
    assert visible == set(shared), (visible, shared)
    def history(session):
        return reader_rpc(port, share, 'session/events', {
            'request': {'address': {'kind': 'session', 'sessionId': session}},
        })
    status, body = history(shared[0])
    assert status == 200 and body['result']['ok'], (status, body)
    refusals = {}
    for name, (status, body) in [('outsideSession', history(outside)),
                                 ('ownerManagement', reader_rpc(port, share, 'liveshareShares/list', {}))]:
        rejection = body.get('result', body)
        code = rejection.get('error', {}).get('code')
        assert status in [200,403] and rejection.get('ok') is False, (status, body)
        assert code and code not in ['gateway/arguments-invalid','gateway/internal'], (status,body)
        refusals[name] = code
    evidence['readerBeforeRevocation'] = {
        'anonymousRefused': True, 'htmlBytes': len(html), 'visibleSessionIds': sorted(visible),
        'accessRefusalCodes': refusals, 'sharedHistoryReadable': True,
    }
    if model:
        with support['model_key'](device):
            verify_viewer_turn(device, port, share, shared[0], evidence)
        evidence['testModelKeyRemoved'] = True
    status, body = relay_call(port, share, {}, path='/__fixture/revoke', token='fixture-admin')
    assert status == 200 and body['revoked'] is True
    status, body = relay_call(port, share, {'op': 'asset', 'path': ''})
    assert (status, body.get('error')) == (403, 'viewer-not-authorized'), (status, body)
    evidence['ownerAppliedLiveRevocation'] = True


def run(device, output, model):
    node = Path(os.environ.get('DEVECO_HOME', '/Applications/DevEco-Studio.app/Contents'))/'tools/node/bin/node'
    fixture = Path(__file__).with_name('fixtures')/'liveshare-relay.cjs'
    name = 'mh-share-relay-'+uuid.uuid4().hex[:10]
    folder = 'alpine/workspace-native/'+name
    workspace_path = support['WORKSPACE']+'/'+name
    base = 'http://127.0.0.1:19769'
    bridge = ('tcp:19643', 'tcp:19592')
    temp = '/data/local/tmp/'+name
    paths = [flow['PROFILE']+'/'+part for part in ('package.json', 'pnpm-lock.yaml', 'cordis.patch.yml')]
    paths.append('mobile-harness-boot.json')
    proc = None
    reverse = None
    workspace = None
    share = None
    sessions = []
    saved, evidence = {}, {}
    assert 'Forwardport result:OK' in device.hdc('fport', *bridge)
    try:
        device.ready('normal')
        saved = {path: agent['read_bytes'](device, path) for path in paths}
        assert not flow['market']['catalog'](device, NAME)['enabled']
        flow['flow']['switch'](device, NAME, True)
        proc = subprocess.Popen([str(node), str(fixture), str(ws_module())], stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True)
        assert select.select([proc.stdout], [], [], 5)[0], 'Relay did not report a bound port'
        relay_port = int(proc.stdout.readline())
        candidate = ('tcp:19769', f'tcp:{relay_port}')
        assert 'Forwardport result:OK' in device.hdc('rport', *candidate)
        reverse = candidate
        device.app('mkdir '+folder)
        state = workspace_path+'/owner-shares.json'
        patch = saved[paths[2]].rstrip() + ('\n- id: liveshare-share-host\n  config: '+
                                          json.dumps({'ownerStateFile': state})+'\n').encode()
        expiry = (datetime.now(timezone.utc)+timedelta(hours=1)).isoformat()
        credential = {'relay': base, 'credential': 'fixture-payload.fixture-signature',
                      'expiresAt': expiry, 'subjectId': 'owner'}
        lsp['restore_bytes'](device, folder+'/owner-credential.json', json.dumps(credential).encode(), temp+'-credential')
        device.stop()
        lsp['restore_bytes'](device, paths[2], patch, temp+'-patch')
        device.start()
        device.ready('normal')
        assert owner(device, 'setRelay', {'relayUrl': base})['effective'] == base
        evidence['reachable'] = device.rpc('liveshareShares/testRelay', {})
        assert evidence['reachable'] == {'ok': True, 'httpReachable': True, 'blocking': False}
        registered = device.rpc('workspace/create', {'request': {'path': workspace_path}})
        assert registered['created']
        workspace = registered['workspace']['workspaceId']
        for _ in range(3):
            sessions.append(device.rpc('session/create', {'request': {'workspaceId': workspace}})['sessionId'])
        evidence['authorized'] = owner(device, 'testPublish', {'sessionId': sessions[0]})
        assert evidence['authorized'] == {'ok': True, 'blocking': False}, evidence['authorized']
        created = owner(device, 'create', {'sessionId': sessions[0], 'sessionTitle': 'Loopback DSH fixture',
                                           'sessionMode': 'view', 'allowsFork': False, 'accessMode': 'selected',
                                           'allowedSubjectIds': ['fixture:local:reader']})
        share = created['shareId']
        evidence['created'] = created
        assert created['link'] == base+'/?shareId='+share and created['sessionMode'] == 'view'
        expanded = owner(device, 'addSessions', {'shareId': share, 'sessionIds': [sessions[1]]})
        assert expanded['sessionIds'] == sessions[:2], expanded
        evidence['addedSecondSource'] = True
        flow['flow']['restart'](device)
        until = time.monotonic()+18
        while time.monotonic() < until:
            rows = device.rpc('liveshareShares/list', {})['shares']
            if len(rows) == 1 and rows[0]['online']:
                assert rows[0]['shareId'] == share and rows[0]['sessionIds'] == sessions[:2], rows
                break
            time.sleep(.25)
        else:
            raise AssertionError('LiveShare did not reconnect after restarting the Host')
        evidence['restoredOnlineSources'] = rows[0]['sessionIds']
        verify_reader(device, relay_port, share, sessions[:2], sessions[2], evidence, model)
        evidence['stop'] = owner(device, 'stop', {'shareId': share})
        assert evidence['stop'] == {'ok': True} and device.rpc('liveshareShares/list', {}) == {'shares': []}
        status, _ = relay_call(relay_port, share, {'op': 'asset', 'path': ''})
        assert status == 404
        evidence['stoppedShareUnavailable'] = True
        share = None
        disabled = device.rpc('pluginManager/setBundleEnabled', {'name': NAME, 'enabled': False})
        assert disabled['application'] == 'applied', disabled
        until = time.monotonic()+8
        while time.monotonic() < until:
            events = device.app('cat alpine/tmp/dsh-native-timeline.log')
            if 'liveshare-worker-stopped' in events:
                evidence['gatewayThreadStopped'] = True
                break
            time.sleep(.1)
        else:
            raise AssertionError('Disabling LiveShare did not stop the gateway worker')
    finally:
        try:
            try:
                if share:
                    owner(device, 'stop', {'shareId': share})
                for session in sessions:
                    device.rpc('workspace/archiveSession', {'request': {'sessionId': session}})
                if workspace:
                    assert device.rpc('workspace/delete', {'request': {'workspaceId': workspace}}) == {'deleted': True}
            finally:
                if saved:
                    device.stop()
                    device.app('rm -rf '+folder)
                    for i, (path, body) in enumerate(saved.items()):
                        lsp['restore_bytes'](device, path, body, temp+str(i))
                    device.start()
                    evidence['restoredReadyMs'] = device.ready('normal')
                    assert all(agent['read_bytes'](device, path) == body for path, body in saved.items())
                    evidence['configRestored'] = True
        finally:
            if reverse:
                device.hdc('fport', 'rm', *reverse)
            device.hdc('fport', 'rm', *bridge)
            if proc:
                proc.terminate()
                messages, stderr = proc.communicate(timeout=5)
                evidence['relayMessages'] = [json.loads(row) for row in messages.splitlines()]
                if stderr:
                    evidence['relayError'] = stderr
            output.write_text(json.dumps(evidence, indent=2)+'\n')
    created_id = evidence['created']['shareId']
    messages = evidence['relayMessages']
    assert sum(row.get('registered') == created_id for row in messages) >= 2, messages
    assert any(row.get('deleted') == created_id for row in messages), messages
    assert any(row.get('closed') == created_id and row.get('code') == 1000 for row in messages), messages


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('target')
    parser.add_argument('output', type=Path)
    parser.add_argument('--model', action='store_true', help='Also send an owned prompt to the actual model')
    args = parser.parse_args()
    if args.model and not os.environ.get('MH_TEST_DEEPSEEK_API_KEY'):
        parser.error('--model requires MH_TEST_DEEPSEEK_API_KEY')
    run(support['Emulator'](args.target, 19643), args.output, args.model)
