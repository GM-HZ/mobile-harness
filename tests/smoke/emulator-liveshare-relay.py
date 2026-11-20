"""Exercise the real LiveShare gateway and owner authorization with an isolated Relay."""
import argparse
import base64
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
import random
import re
from pathlib import Path
import runpy
import select
import subprocess
import time
import uuid
from urllib.error import HTTPError
from urllib.request import Request, urlopen

flow = runpy.run_path(str(Path(__file__).with_name('emulator-personalized-recommendations.py')))
translation = runpy.run_path(str(Path(__file__).with_name('emulator-cot-translation.py')))
support, agent, lsp = (flow[name] for name in ['support', 'agent', 'lsp'])
ws_module = runpy.run_path(str(Path(__file__).with_name('emulator-ptc-approval.py')))['ws_module']
NAME = '@deepseek-ai/dsh-experimental-liveshare'
HDC = os.environ.get('HARMONY_HDC', '/Applications/DevEco-Studio.app/Contents/sdk/default/openharmony/toolchains/hdc')
PROTOCOL_PACKAGE = ('alpine/.dsh-0.2.2-rc.5/dsh/node_modules/@deepseek-ai/'
                    'dsh-experimental-liveshare-protocol/lib/index.js')
CARRIER_SCRIPT = """
import fs from 'node:fs';
const [source, shareId, sessionId] = JSON.parse(fs.readFileSync(0, 'utf8'));
const { viewerCarrierScript } = await import('data:text/javascript;base64,' + source);
console.log(viewerCarrierScript({ basePath: '', shareId, sessionId, readTimeoutMs: 28000 }));
"""


def owner(device, method, request, timeout=25):
    return device.rpc('liveshareShares/'+method, {'request': request}, timeout=timeout)


BASE_OVERRIDE = None
DEVICE_BASE = None
RELAY_HOST_PORT = None
VIEWER_TOKEN = 'fixture-viewer'
ADMIN_TOKEN = 'fixture-admin'


def clear_forward(hdc_call, listen):
    """Remove any existing forward ruler with this device listen port."""
    try:
        listing = hdc_call('fport', 'ls')
    except Exception:
        return
    for line in listing.splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[1] == listen:
            try:
                hdc_call('fport', 'rm', parts[1], parts[2])
            except Exception:
                pass


def relay_base(port):
    if BASE_OVERRIDE:
        return BASE_OVERRIDE
    return f'http://127.0.0.1:{port}'


def relay_call(port, share, payload, *, token='viewer-default', path='/__share/rpc'):
    if token == 'viewer-default':
        token = VIEWER_TOKEN
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = 'Bearer '+token
    request = Request(relay_base(port) + path + f'?shareId={share}',
                      data=json.dumps(payload).encode(), headers=headers)
    try:
        with urlopen(request, timeout=8) as response:
            return response.status, json.load(response)
    except HTTPError as error:
        return error.code, json.load(error)


def reader_rpc(port, share, method, args):
    body = {'type': 'client-request', 'rpcId': str(uuid.uuid4()), 'method': method, 'payload': {'args': args}}
    return relay_call(port, share, {'op': 'call', 'path': '/api/'+method, 'body': body})


def viewer_turn(device, port, share, session, content):
    request_id = str(uuid.uuid4())
    status, body = reader_rpc(port, share, 'session/prompt', {'request': {
        'sessionId': session, 'requestId': request_id, 'mode': 'queue', 'content': content,
    }})
    assert status == 200 and body['result']['ok'], (status, body)
    return observed_viewer_turn(device, share, session, request_id)


def observed_viewer_turn(device, share, session, request_id):
    deadline = time.monotonic()+60
    while time.monotonic() < deadline:
        rows = support['events'](device, session)
        submitted = next((row for row in rows if row['type'] == 'user/message'
                          and row['data']['source'].get('rpcId') == request_id), None)
        if submitted:
            messages = [row for row in rows if row['seq'] > submitted['seq']]
            ended = next((row['data']['reason']['kind'] for row in messages if row['type'] == 'turn/end'), None)
            if ended:
                assert ended == 'completed'
                assert not any(row['type'] == 'tool/call' for row in messages)
                principal = submitted['data']['source']['principal']
                assert principal == {'kind': 'share-viewer', 'shareId': share,
                                     'actor': {'providerId': 'fixture', 'tenantId': 'local',
                                               'subjectId': 'reader'}}, principal
                return submitted['data'], agent['assistant_texts'](messages).strip(), ended
        time.sleep(.2)
    raise AssertionError('The specific viewer prompt did not complete')


def verify_viewer_turn(device, port, share, session, evidence):
    nonce = 'VIEWER_' + uuid.uuid4().hex.upper()
    text = 'Reply only with '+nonce+'. Use no tools.'
    device.rpc('session/selectModel', {'request': {'sessionId': session, 'provider': 'deepseek-official',
        'model': 'deepseek-flash', 'reasoningEffort': 'off'}})
    message, reply, ended = viewer_turn(device, port, share, session, [{'type': 'text', 'text': text}])
    assert reply == nonce
    evidence['actualViewerModelTurn'] = {'principal': message['source']['principal'],
                                         'exactReply': True, 'endReason': ended}


def verify_shared_attachments(device, port, share, session, evidence):
    vision = runpy.run_path(str(Path(__file__).with_name('emulator-deepseek-vision.py')))
    colors = ('green', 'blue', 'red', 'yellow')
    blobs = [vision['sample'](*colors[:2]), vision['sample'](*colors[2:])]
    receipts = [vision['upload'](device, session, f'share-image-{index}.png', image)
                for index, image in enumerate(blobs)]
    reply, reason, attached = vision['execute'](device, session, receipts)
    assert reply.lower().split() == list(colors), reply

    def read_images():
        images = []
        for receipt in receipts:
            attachment = receipt['image']
            request = {'request': {'sessionId': session, 'attachment': attachment}}
            status, body = reader_rpc(port, share, 'session/attachment', request)
            assert status == 200 and body['result']['ok'], (status, list(body))
            shared = body['result']['value']
            assert shared['attachment']['attachmentId'] == attachment['attachmentId']
            assert shared == device.rpc('session/attachment', request)
            images.append(hashlib.sha256(base64.b64decode(shared['data'], validate=True)).hexdigest())
        return images

    checksums = read_images()
    assert len(set(checksums)) == len(blobs)
    flow['flow']['restart'](device)
    until = time.monotonic()+18
    while time.monotonic() < until:
        rows = device.rpc('liveshareShares/list', {})['shares']
        if any(row['shareId'] == share and row['online'] for row in rows):
            break
        time.sleep(.25)
    else:
        raise AssertionError('LiveShare did not reconnect for the attachment read')
    assert read_images() == checksums
    evidence['sharedAttachments'] = {'count': len(blobs), 'modelReply': reply,
        'turnEndReason': reason['kind'], 'attachmentIds': attached,
        'viewerBytesMatchedOwner': True, 'viewerBytesRestoredAfterRestart': True,
        'sha256': checksums}


def verify_guest_uploads(device, port, share, session, outside, html, evidence):
    vision = runpy.run_path(str(Path(__file__).with_name('emulator-deepseek-vision.py')))
    marker = ('Guest attachment ' + uuid.uuid4().hex).encode()
    filename = 'guest-note.txt'
    colors = random.SystemRandom().sample(list(vision['COLORS']), len(vision['COLORS']))
    blobs = [vision['sample'](*colors[:2]), vision['sample'](*colors[2:])]
    files = [{'data': base64.b64encode(marker).decode(), 'name': filename}] + [
        {'data': base64.b64encode(blob).decode(), 'name': f'guest-{index}.png', 'mediaType': 'image/png'}
        for index, blob in enumerate(blobs)
    ]
    protocol = ('alpine/.dsh-0.2.2-rc.5/dsh/node_modules/@deepseek-ai/'
                'dsh-experimental-liveshare-protocol/lib/index.js')
    carrier = base64.b64encode(agent['read_bytes'](device, protocol)).decode()
    fixture = Path(__file__).with_name('fixtures')/'liveshare-viewer-upload.cjs'
    node = Path(os.environ.get('DEVECO_HOME', '/Applications/DevEco-Studio.app/Contents'))/'tools/node/bin/node'
    run = subprocess.run([str(node), str(fixture)], input=json.dumps({
        'base': f'http://127.0.0.1:{port}', 'share': share, 'session': session, 'outside': outside,
        'html': html.decode(), 'carrier': carrier, 'files': files,
    }), text=True, capture_output=True, timeout=30)
    assert run.returncode == 0, run.stderr
    result = json.loads(run.stdout)
    file, *images = result['staged']
    assert file['file']['name'] == filename and file['file']['bytes'] == len(marker)
    assert all((image['image']['width'], image['image']['height']) == (vision['WIDTH'], vision['HEIGHT'])
               for image in images), images
    prompt = ('Read the two images in order. Each image has two solid vertical halves. '
              'Return only the four English color names, separated by spaces, left then right for each image. '
              'Ignore the text file. Do not use tools.')
    content = [{'type': 'file', 'receiptId': upload['receiptId']} for upload in result['staged']]
    content.append({'type': 'text', 'text': prompt})
    message, reply, end = viewer_turn(device, port, share, session, content)
    assert reply.lower().split() == colors, (colors, reply)
    attachments = [block['attachment'] for block in message['content'] if block['type'] == 'image']
    assert attachments == [image['image'] for image in images]
    assert any(file['file']['attachmentId'] in json.dumps(block) for block in message['content']), message['content']
    for attachment in attachments:
        request = {'request': {'sessionId': session, 'attachment': attachment}}
        status, body = reader_rpc(port, share, 'session/attachment', request)
        assert status == 200 and body['result']['ok'], (status, list(body))
        assert body['result']['value'] == device.rpc('session/attachment', request)
    evidence['guestSubmittedAttachments'] = {
        'fileName': filename, 'fileBytes': file['file']['bytes'], 'expectedColors': colors, 'modelReply': reply,
        'endReason': end, 'visitorPrincipal': message['source']['principal'], 'imageCount': len(attachments),
        'outsideUploadsRefused': result['refused'], 'allReceiptsConsumedByPrompt': True,
        'servedHookAndPackagedCarrier': True, 'cancelledBeforeTransfer': result['cancelledBeforeTransfer'],
        'maxConcurrentRelayUploads': result['peak'],
    }


def program_result(device, port, share, session, args):
    req = str(uuid.uuid4())
    prompt = 'Actually call run_code exactly once with precisely ' + json.dumps(args) + '. Use no other tools. Report the result.'
    status, body = reader_rpc(port, share, 'session/prompt', {'request': {
        'sessionId': session, 'requestId': req, 'mode': 'queue', 'content': [{'type': 'text', 'text': prompt}],
    }})
    assert status == 200 and body['result']['ok'], (status, body)
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        rows = support['events'](device, session)
        anchor = next((row for row in rows if row['type'] == 'user/message' and
                       row['data']['source'].get('rpcId') == req), None)
        if anchor:
            source = anchor['data']['source']['principal']
            assert source['kind'] == 'share-viewer' and source['shareId'] == share
            following = [row for row in rows if row['seq'] > anchor['seq']]
            end = next((row for row in following if row['type'] == 'turn/end'), None)
            if end:
                assert end['data']['reason']['kind'] == 'completed', end
                calls = [row['data'] for row in following if row['seq'] < end['seq'] and row['type'] == 'tool/call']
                call, = calls
                assert call['name'] == 'run_code' and json.loads(call['arguments']) == args, call
                result, = (row['data']['message'] for row in following if row['seq'] < end['seq'] and
                           row['type'] == 'tool/result' and row['data']['message']['toolCallId'] == call['callId'])
                return result, end['seq']
        time.sleep(.15)
    raise AssertionError('The viewer program did not finish')


def program_trace(device):
    return [json.loads(row) for row in device.app('cat alpine/tmp/dsh-native-timeline.log').splitlines()]


def scoped_program(device, port, share, session, args, marker, mode, *, fork=False):
    offset = len(program_trace(device))
    result, seq = program_result(device, port, share, session, args)
    text = agent['toolkit']['texts']([result])
    assert not result['isError'] and marker in text, result
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        rows = program_trace(device)[offset:]
        policies = [row for row in rows if row['event'] == 'liveshare-ptc-policy']
        entered = [row for row in rows if row['event'] == 'ptc-worker-admitted']
        reaped = {row['id'] for row in rows if row['event'] == 'ptc-worker-reaped'}
        if entered and entered[0]['id'] in reaped:
            policy, = policies
            worker, = entered
            assert policy['mode'] == worker['mode'] == mode and policy['fork'] == fork, rows
            return seq
        time.sleep(.12)
    raise AssertionError('The scoped PTC worker did not exit')


def verify_program_policy(device, port, share, session, folder, sessions, evidence):
    result = evidence['programPolicy'] = {}
    mark = 'OWNED_'+uuid.uuid4().hex.upper()
    device.app(f'printf %s {mark} > {folder}/shared-fixture.txt')
    source = {'sessionId': session, 'sessionTitle': 'Scoped write fixture', 'sessionMode': 'write',
              'allowsFork': True, 'accessMode': 'selected', 'allowedSubjectIds': ['fixture:local:reader']}
    other = owner(device, 'create', source)['shareId']
    try:
        read = {'description': 'Read the shared fixture', 'code':
                'const fs = await import("node:fs/promises"); return await fs.readFile("shared-fixture.txt", "utf8");'}
        at_seq = scoped_program(device, port, share, session, read, mark, 'read-only')
        result['viewRemainsReadOnlyAlongsideWriteShare'] = True
        nested = {'description': 'Check the shared file tool authorization', 'code':
                  'try { await tools.write({file_path:"readonly-output.txt",content:"fixture"}); '
                  'return "UNEXPECTED_WRITE"; } catch (error) { return String(error); }'}
        scoped_program(device, port, share, session, nested, 'this share does not allow writing', 'read-only')
        assert device.app('test ! -e '+folder+'/readonly-output.txt && printf ABSENT') == 'ABSENT'
        result['nestedWriteDeniedAcrossViewerTiers'] = True
        offset = len(program_trace(device))
        denied, _ = program_result(device, port, share, session, {
            'description': 'Check the share escalation policy', 'code': 'return "SCOPE_CHECK";',
            'sandbox_permissions': 'danger-full-access', 'justification': 'Only run the isolated scope check.',
        })
        assert denied['isError'] and 'cannot request wider sandbox permissions' in agent['toolkit']['texts']([denied]), denied
        assert not any(row['event'] == 'ptc-worker-admitted' for row in program_trace(device)[offset:])
        result['escalationDeniedBeforeWorkerLaunch'] = True
        write = {'description': 'Write the fixture inside the shared directory', 'code':
                 'const fs = await import("node:fs/promises"); await fs.writeFile("owned-output.txt", '
                 + json.dumps(mark) + '); return "SCOPED_WRITE";'}
        scoped_program(device, port, other, session, write, 'SCOPED_WRITE', 'workspace-write')
        assert device.app('cat '+folder+'/owned-output.txt') == mark
        result['boundedWriteCompleted'] = True
        fork_request = {'request': {'sessionId': session, 'atSeq': at_seq, 'operationId': str(uuid.uuid4())}}
        status, response = reader_rpc(port, share, 'session/fork', fork_request)
        assert status == 200 and response['result']['ok'], (status, response)
        child = response['result']['value']['sessionId']
        sessions.append(child)
        status, replay = reader_rpc(port, share, 'session/fork', fork_request)
        assert status == 200 and replay['result']['value']['sessionId'] == child, replay
        device.rpc('session/selectModel', {'request': {'sessionId': child, 'provider': 'deepseek-official',
                                                        'model': 'deepseek-flash', 'reasoningEffort': 'off'}})
        scoped_program(device, port, share, child, read, mark, 'read-only', fork=True)
        result['readOnlyForkAndReplay'] = True
        result['childSessionId'] = child
        offset = len(program_trace(device))
        confirmed, _ = agent['tool'](device, session, 'run_code', read)
        assert mark in agent['toolkit']['texts']([confirmed])
        owner_rows = program_trace(device)[offset:]
        assert not any(row['event'] == 'liveshare-ptc-policy' for row in owner_rows), owner_rows
        assert any(row['event'] == 'ptc-worker-admitted' and row['mode'] == 'workspace-write' for row in owner_rows)
        result['ownerPolicyUnaffected'] = True
    finally:
        assert owner(device, 'stop', {'shareId': other}) == {'ok': True}


def verify_reader(device, port, share, shared, outside, evidence, model, program_check, attachments, guest_check,
                  cross_device_check=None):
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
    if model or program_check or attachments or guest_check:
        with support['model_key'](device):
            verify_viewer_turn(device, port, share, shared[0], evidence)
            if attachments:
                verify_shared_attachments(device, port, share, shared[0], evidence)
            if guest_check:
                guest_check(device, port, share, shared[0], outside, html, evidence)
            if program_check:
                program_check()
        evidence['testModelKeyRemoved'] = True
    if cross_device_check:
        # Prove the second device viewer while the share still authorizes readers;
        # the revocation below deliberately invalidates it afterwards.
        cross_device_check()
        evidence['crossDeviceBeforeRevocation'] = True
    status, body = relay_call(port, share, {}, path='/__fixture/revoke', token=ADMIN_TOKEN)
    assert status == 200 and body['revoked'] is True
    status, body = relay_call(port, share, {'op': 'asset', 'path': ''})
    assert (status, body.get('error')) == (403, 'viewer-not-authorized'), (status, body)
    evidence['ownerAppliedLiveRevocation'] = True
    if program_check:
        status, body = history(evidence['programPolicy']['childSessionId'])
        assert (status, body.get('error')) == (403, 'viewer-not-authorized'), (status, body)
        evidence['revokedForkHistoryRefused'] = True


def verify_owner_login(device, title, evidence):
    ui = translation['ui']
    with translation['browser'](device) as browser:
        translation['open_session'](device, browser, title)
    ui['tap'](device, ui['wait_control'](device, {'分享', 'Share'}, 'button'))
    ui['wait_control'](device, {'分享会话', 'Share session'}, 'dialog')
    ui['tap'](device, ui['wait_control'](device, {'登录', 'Sign in'}, 'button'))
    limit = time.monotonic() + 15
    while time.monotonic() < limit:
        rows = ui['controls'](device)
        blocked = next((row['text'] for row in rows if '登录地址不受支持' in row['text']), None)
        if blocked:
            evidence['nativeNavigationBlocked'] = blocked
            ui['tap'](device, ui['wait_control'](device, {'返回聊天'}))
            raise AssertionError('ArkWeb blocked the LiveShare authorization address')
        approval = ui['find'](rows, {'Authorize fixture owner'}, 'button')
        if approval:
            ui['tap'](device, approval)
            break
        time.sleep(.25)
    else:
        raise AssertionError('ArkWeb did not render the Relay authorization')
    ui['wait_control'](device, {'Fixture Relay Owner'})
    identity = owner(device, 'identity', {})
    assert identity['state'] == 'verified' and identity['displayName'] == 'Fixture Relay Owner', identity
    evidence['arkwebOwnerVerified'] = True


def fixture_log(port):
    request = Request(relay_base(port) + '/__fixture/log', headers={'Authorization': 'Bearer ' + ADMIN_TOKEN})
    try:
        with urlopen(request, timeout=5) as response:
            return json.load(response)['records']
    except Exception:
        return []


def browser_tap(target, labels=('浏览器', '极简浏览')):
    """Tap the first clickable node whose text is one of the given labels."""
    dump = 'cat /data/local/tmp/mh-liveshare-ui.json'
    subprocess.run([HDC, '-t', target, 'shell',
                    'uitest dumpLayout -p /data/local/tmp/mh-liveshare-ui.json >/dev/null 2>&1'],
                   check=False, timeout=60)
    try:
        raw = subprocess.check_output([HDC, '-t', target, 'shell', dump], text=True, timeout=60)
    except subprocess.CalledProcessError:
        return False
    nodes = []
    def walk(node):
        attributes = node.get('attributes', {})
        if attributes.get('text') in labels:
            nodes.append(attributes.get('bounds'))
        for child in node.get('children', []):
            walk(child)
    try:
        walk(json.loads(raw))
    except ValueError:
        return False
    if not nodes:
        return False
    values = re.findall(r'-?\d+', nodes[0])
    x = (int(values[0]) + int(values[2])) // 2
    y = (int(values[1]) + int(values[3])) // 2
    subprocess.run([HDC, '-t', target, 'shell', 'uitest', 'uiInput', 'click', str(x), str(y)],
                   check=False, timeout=60)
    return True


def cross_device_viewer(device, relay_port, share, sessions, target, evidence):
    """Read the shared session from the official viewer page on a second device."""
    node = Path(os.environ.get('DEVECO_HOME', '/Applications/DevEco-Studio.app/Contents'))/'tools/node/bin/node'
    source = agent['read_bytes'](device, PROTOCOL_PACKAGE)
    carrier = subprocess.run([str(node), '--input-type=module', '-e', CARRIER_SCRIPT],
                             input=json.dumps([base64.b64encode(source).decode(), share, str(sessions[0])]),
                             text=True, capture_output=True, check=True).stdout.strip()
    assert 'viewerCarrierScript' not in carrier and '__DSH_LIVESHARE_VIEWER__' in carrier
    config = json.dumps({'carrier': carrier, 'sessionId': sessions[0],
                         'ownerDisplayName': 'Fixture Relay Owner'}).encode()
    request = Request(relay_base(relay_port) + '/__fixture/viewer', data=config,
                      headers={'Authorization': 'Bearer ' + ADMIN_TOKEN, 'Content-Type': 'application/json'})
    with urlopen(request, timeout=8) as response:
        assert json.load(response) == {'ok': True}

    def hdc(*args):
        return subprocess.check_output([HDC, '-t', target, *args], text=True, timeout=90).strip()

    reverse = None
    if RELAY_HOST_PORT:
        reverse = ('tcp:19769', f'tcp:{RELAY_HOST_PORT}')
    elif relay_port:
        reverse = ('tcp:19769', f'tcp:{relay_port}')
    if reverse:
        clear_forward(hdc, reverse[0])
        assert 'Forwardport result:OK' in hdc('rport', *reverse)
    title = 'MH cross-device viewer ' + uuid.uuid4().hex[:6]
    assert device.rpc('session/rename', {'request': {'sessionId': sessions[0], 'title': title}})['title'] == title
    try:
        page = None
        for attempt in range(3):
            # The device reaches the internally spawned fixture through its 19769 rport;
            # external modes provide their own device-visible base.
            page_base = DEVICE_BASE or 'http://127.0.0.1:19769'
            opened = hdc('shell', f"aa start -U '{page_base}/?shareId={share}'")
            print('cross-device: start ability ->', opened, flush=True)
            deadline = time.monotonic() + 45
            while time.monotonic() < deadline:
                records = fixture_log(relay_port)
                page = next((row for row in records if row.get('viewerPageServed') and row.get('share') == share), None)
                if page:
                    print('cross-device: viewer page served', json.dumps(page, ensure_ascii=False)[:400], flush=True)
                    break
                browser_tap(target)
                time.sleep(1)
            if page:
                time.sleep(5)
                subprocess.run([HDC, '-t', target, 'shell',
                                'uitest dumpLayout -p /data/local/tmp/mh-liveshare-viewer.json >/dev/null 2>&1'],
                               check=False, timeout=60)
                raw = hdc('shell', 'cat /data/local/tmp/mh-liveshare-viewer.json 2>/dev/null || true')
                texts = [text for text in re.findall(r'"text":"([^"]*)"', raw) if text]
                print('cross-device: viewer ui after page', texts[:16], flush=True)
            if page:
                break
            hdc('shell', 'aa force-stop com.huawei.hmos.browser')
            time.sleep(2)
        assert page, fixture_log(relay_port)[-8:]
        assert 'HuaweiBrowser' in page['userAgent'] or 'ArkWeb' in page['userAgent'], page
        deadline = time.monotonic() + 150
        while time.monotonic() < deadline:
            records = fixture_log(relay_port)
            rpc = [row for row in records if row.get('viewerRpc') == 'call:/api/session/list'
                   and row.get('viaCookie')]
            assets = [row for row in records if row.get('viewerAsset') and row.get('status') == 200]
            context = [row for row in records if row.get('viewerContext')]
            if rpc and len(assets) >= 3 and context:
                break
            time.sleep(1)
        else:
            raise AssertionError('The second device viewer did not read the share: '
                                 + json.dumps(records[-10:], ensure_ascii=False)[:1200])
        subprocess.run([HDC, '-t', target, 'shell',
                        'uitest dumpLayout -p /data/local/tmp/mh-liveshare-viewer.json >/dev/null 2>&1'],
                       check=False, timeout=60)
        deadline = time.monotonic() + 150
        texts = []
        collected = []
        tapped = set()
        while time.monotonic() < deadline:
            subprocess.run([HDC, '-t', target, 'shell',
                            'uitest dumpLayout -p /data/local/tmp/mh-liveshare-viewer.json >/dev/null 2>&1'],
                           check=False, timeout=60)
            raw = hdc('shell', 'cat /data/local/tmp/mh-liveshare-viewer.json 2>/dev/null || true')
            texts = [text for text in re.findall(r'"text":"([^"]*)"', raw) if text]
            collected.extend(text for text in texts if text not in collected)
            if title in collected or any('新会话' in text for text in collected):
                break
            for label in ('打开侧边栏', '打开右侧边栏', '选择工作区'):
                if label in texts and label not in tapped:
                    browser_tap(target, (label,))
                    tapped.add(label)
                    time.sleep(2)
                    break
            time.sleep(2)
        evidence['crossDeviceViewer'] = {
            'target': target, 'pageUserAgent': page['userAgent'],
            'viewerContextRequests': len(context), 'viewerAsset200': len(assets),
            'viewerSessionListCalls': len(rpc), 'visibleTexts': collected[:24],
            'ownerManagementAttempted': any(row.get('viewerRpc') == 'call:/api/liveshareShares/list'
                                            and row.get('viaCookie') for row in records),
            'sharedTitle': title, 'sharedTitleVisible': title in collected,
        }
        assert collected, 'The viewer page rendered no text on the second device'
        assert any('观看者' in text or '仅可查看' in text for text in collected), collected
        assert any('新会话' in text or title == text for text in collected), \
            ['the viewer sidebar shows no session row', collected[:24]]
        assert not evidence['crossDeviceViewer']['ownerManagementAttempted'], evidence['crossDeviceViewer']
    finally:
        subprocess.run([HDC, '-t', target, 'shell', 'aa force-stop com.huawei.hmos.browser'],
                       check=False, timeout=60)
        if reverse:
            subprocess.run([HDC, '-t', target, 'fport', 'rm', *reverse], check=False, timeout=60)


def run(device, output, model, owner_login, host_port, program_policy, attachments=False, guest_check=None,
        cross_device_target=None, relay_url=None, relay_host_port=None, admin_token=None, viewer_token=None,
        relay_call_url=None):
    global BASE_OVERRIDE, DEVICE_BASE, RELAY_HOST_PORT, ADMIN_TOKEN, VIEWER_TOKEN
    if admin_token:
        ADMIN_TOKEN = admin_token
    if viewer_token:
        VIEWER_TOKEN = viewer_token
    RELAY_HOST_PORT = relay_host_port
    node = Path(os.environ.get('DEVECO_HOME', '/Applications/DevEco-Studio.app/Contents'))/'tools/node/bin/node'
    fixture = Path(__file__).with_name('fixtures')/'liveshare-relay.cjs'
    name = 'mh-share-relay-'+uuid.uuid4().hex[:10]
    folder = 'alpine/workspace-native/'+name
    workspace_path = support['WORKSPACE']+'/'+name
    base = 'http://127.0.0.1:19769'
    bridge = (f'tcp:{host_port}', 'tcp:19592')
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
        saved = {path: translation['profile_bytes'](device, path) for path in paths}
        assert not flow['market']['catalog'](device, NAME)['enabled']
        flow['flow']['switch'](device, NAME, True)
        relay_port = None
        if relay_url:
            base = relay_url.rstrip('/')
            DEVICE_BASE = base
            BASE_OVERRIDE = (relay_call_url or relay_url).rstrip('/')
            evidence['externalRelay'] = {'device': base, 'hostCalls': BASE_OVERRIDE}
            if relay_host_port:
                candidate = ('tcp:19769', f'tcp:{relay_host_port}')
                clear_forward(device.hdc, candidate[0])
                assert 'Forwardport result:OK' in device.hdc('rport', *candidate)
                reverse = candidate
            if owner_login:
                flow['flow']['switch'](device, translation['flow']['BUNDLE'], True)
                flow['flow']['switch'](device, translation['inspector']['NAME'], True)
            try:
                evidence['relayLogBaseline'] = len(fixture_log(relay_port))
            except Exception:
                evidence['relayLogBaseline'] = 0
        else:
            command = [str(node), str(fixture), str(ws_module())]
            if owner_login:
                flow['flow']['switch'](device, translation['flow']['BUNDLE'], True)
                flow['flow']['switch'](device, translation['inspector']['NAME'], True)
                command.append('--owner-login')
            environment = dict(os.environ)
            if cross_device_target:
                environment['MH_RELAY_PAGE_DUMP'] = '/tmp/mh-liveshare-viewer-page.html'
            proc = subprocess.Popen(command, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, text=True, env=environment)
            assert select.select([proc.stdout], [], [], 5)[0], 'Relay did not report a bound port'
            relay_port = int(proc.stdout.readline())
            candidate = ('tcp:19769', f'tcp:{relay_port}')
            clear_forward(device.hdc, candidate[0])
            assert 'Forwardport result:OK' in device.hdc('rport', *candidate)
            reverse = candidate
        device.app('mkdir '+folder)
        state = workspace_path+'/owner-shares.json'
        patch = saved[paths[2]].rstrip()
        if patch == b'[]' or patch.endswith(b'\n[]'):
            patch = patch[:-2].rstrip()
        patch += ('\n- id: liveshare-share-host\n  config: ' + json.dumps({'ownerStateFile': state})+'\n').encode()
        if not owner_login:
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
        if owner_login:
            seed = translation['flow']
            title = 'LiveShare authorization ' + name
            archive = seed['archive_bytes'](name, seed['SOURCE_PNG'].read_bytes(), text_title=title)
            status, uploaded = seed['upload'](device, workspace, archive)
            assert status == 200 and uploaded[-1]['outcome']['ok'], (status, uploaded[-1])
            sessions.extend(uploaded[-1]['outcome']['value']['sessionIds'])
            assert 1 <= len(sessions) <= 2
        for _ in range(3 - len(sessions)):
            args = {'workspaceId': workspace}
            if program_policy and not sessions:
                args['agentPreset'] = 'ptc'
            sessions.append(device.rpc('session/create', {'request': args})['sessionId'])
        if owner_login:
            with support['model_key'](device):
                catalog = device.rpc('session/modelCatalog', {})
                default = catalog['default']
                assert default['provider'] in catalog.get('routableProviders', [default['provider']]), catalog
                device.rpc('session/selectModel', {'request': {'sessionId': sessions[0], 'provider': default['provider'],
                    'model': default['model'], 'reasoningEffort': default.get('reasoningEffort') or 'off'}})
                flow['flow']['restart'](device)
                verify_owner_login(device, title, evidence)
        evidence['authorized'] = owner(device, 'testPublish', {'sessionId': sessions[0]})
        assert evidence['authorized'] == {'ok': True, 'blocking': False}, evidence['authorized']
        created = owner(device, 'create', {'sessionId': sessions[0], 'sessionTitle': 'Loopback DSH fixture',
                                           'sessionMode': 'view', 'allowsFork': program_policy, 'accessMode': 'selected',
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
        def program_check():
            verify_program_policy(device, relay_port, share, sessions[0], folder, sessions, evidence)

        def cross_device_check():
            cross_device_viewer(device, relay_port, share, sessions, cross_device_target, evidence)

        verify_reader(device, relay_port, share, sessions[:2], sessions[2], evidence, model,
                      program_check if program_policy else None, attachments, guest_check,
                      cross_device_check if cross_device_target else None)
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
                        if body is None:
                            device.app('rm -f '+path)
                        else:
                            lsp['restore_bytes'](device, path, body, temp+str(i))
                    device.start()
                    evidence['restoredReadyMs'] = device.ready('normal')
                    assert all(translation['profile_bytes'](device, path) == body for path, body in saved.items())
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
            elif base.startswith(('http://', 'https://')):
                try:
                    records = fixture_log(relay_port)
                    evidence['relayMessages'] = records[evidence.get('relayLogBaseline', 0):]
                except Exception as error:
                    evidence['relayError'] = str(error)[:300]
            output.write_text(json.dumps(evidence, indent=2)+'\n')
    created_id = evidence['created']['shareId']
    messages = evidence['relayMessages']
    if owner_login:
        assert sum(row.get('ownerAuthorizationDisplayed', False) for row in messages) == 1
        assert sum(row.get('ownerCredentialRedeemed', False) and row.get('pkceMatched', False) for row in messages) == 1
    assert sum(row.get('registered') == created_id for row in messages) >= 2, messages
    assert any(row.get('deleted') == created_id for row in messages), messages
    assert any(row.get('closed') == created_id and row.get('code') == 1000 for row in messages), messages


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('target')
    parser.add_argument('output', type=Path)
    parser.add_argument('--model', action='store_true', help='Also send an owned prompt to the actual model')
    parser.add_argument('--owner-login', action='store_true', help='Complete LiveShare owner authorization in ArkWeb')
    parser.add_argument('--program-policy', action='store_true', help='Exercise viewer and fork workspace programs')
    parser.add_argument('--attachments', action='store_true', help='Verify viewer access to shared images after restart')
    parser.add_argument('--guest-uploads', action='store_true', help='Submit visitor files and images through the shared Gateway')
    parser.add_argument('--host-port', type=int, default=19643)
    parser.add_argument('--cross-device', help='Second loopback emulator target that presents the viewer page')
    parser.add_argument('--relay-url', help='External Relay base URL (https:// for public deployment) instead of the local fixture')
    parser.add_argument('--relay-host-port', type=int, help='Host port of an externally started Relay fixture to forward to the device loopback')
    parser.add_argument('--admin-token', default=None, help='Fixture Relay admin token for an external deployment')
    parser.add_argument('--viewer-token', default=None, help='Fixture Relay viewer token for an external deployment')
    parser.add_argument('--relay-call-url', help='Host-visible Relay base URL when it differs from the device URL (local forwarding tests)')
    args = parser.parse_args()
    if (args.model or args.program_policy or args.attachments or args.guest_uploads) and not os.environ.get('MH_TEST_DEEPSEEK_API_KEY'):
        parser.error('The selected live model scenario requires MH_TEST_DEEPSEEK_API_KEY')
    if args.program_policy and args.owner_login:
        parser.error('--program-policy requires the program preset; run the native login test separately')
    run(support['Emulator'](args.target, args.host_port), args.output, args.model, args.owner_login,
        args.host_port, args.program_policy, args.attachments, verify_guest_uploads if args.guest_uploads else None,
        args.cross_device, args.relay_url, args.relay_host_port, args.admin_token, args.viewer_token,
        args.relay_call_url)
