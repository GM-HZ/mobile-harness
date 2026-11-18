"""Import an owned DeepSeek v3 export through the shipped authenticated route."""
import argparse
import base64
from datetime import datetime
import hashlib
import http.client
import io
import json
import os
from pathlib import Path
import runpy
import socket
import time
from urllib.parse import urlencode, urlsplit
import uuid
import zipfile

lsp = runpy.run_path(str(Path(__file__).with_name('emulator-lsp-lifecycle.py')))
agent = lsp['agent']
support = agent['support']
PROFILE = 'alpine/native-benchmark-home/profiles/web'
BUNDLE = '@deepseek-ai/dsh-deepseek-chat-import'
ROUTE = '/api/deepseek-chat-import/archive'
HOST_HEADER = '127.0.0.1:19592'
MODEL = {'provider': 'deepseek-official', 'model': 'deepseek-flash', 'reasoningEffort': 'off'}
ARCHIVE_TIME = '2026-11-11T02:00:00.000Z'
PROMPT_TIME = '2026-11-11T02:00:01.000Z'
ANSWER_TIME = '2026-11-11T02:00:04.000Z'
FILENAMES = ['fixture.png', 'report.pdf']
SOURCE_PNG = Path('vendor/repos/dsh/packages/experimental/skill-badge/assets/dsh-badge.png')


def archive_bytes(marker, png, *, version=3, manifest=True):
    image_id = str(uuid.uuid4())
    path = f'chat_sessions/picture_files/{image_id}_{FILENAMES[0]}'
    text_content = [
        {'type': 'THINK', 'content': 'Search only the archived export context.', 'elapsed_secs': .5},
        {'type': 'TOOL_SEARCH', 'queries': ['archive fixture'],
         'results': [{'url': 'https://example.invalid/fixture', 'title': 'Archived result',
                      'snippet': 'Synthetic archived record', 'published_at': None, 'site_name': None}]},
        {'type': 'RESPONSE', 'content': 'The archive verification code is ' + marker + '.'},
    ]
    files = [
        {'id': image_id, 'file_name': FILENAMES[0], 'file_size': len(png), 'token_usage': 0,
         'inserted_at': PROMPT_TIME, 'export_path': path, 'is_image': True, 'width': 726, 'height': 120},
        {'id': str(uuid.uuid4()), 'file_name': FILENAMES[1], 'file_size': 123, 'token_usage': 0,
         'inserted_at': PROMPT_TIME, 'export_path': None, 'is_image': False},
    ]

    def conversation(cid, title, request, response):
        return {'id': cid, 'title': title, 'inserted_at': ARCHIVE_TIME, 'current_message_id': 2, 'messages': [
            {'id': 1, 'parent_id': None, 'role': 'USER', 'status': 'FINISHED',
             'inserted_at': PROMPT_TIME, 'fragments': request},
            {'id': 2, 'parent_id': 1, 'role': 'ASSISTANT', 'status': 'FINISHED',
             'inserted_at': ANSWER_TIME, 'fragments': response},
            {'id': 3, 'parent_id': 1, 'role': 'ASSISTANT', 'status': 'FINISHED',
             'inserted_at': ANSWER_TIME, 'fragments': [{'type': 'RESPONSE', 'content': 'DISCARDED_BRANCH'}]},
        ]}

    text = conversation('text', '导入：存档核对', [{'type': 'REQUEST', 'content': 'Keep the archive verification code.'}], text_content)
    picture = conversation('picture', '图片与文件卡片',
                           [{'type': 'FILE', 'files': files}, {'type': 'REQUEST', 'content': 'Describe the attached picture.'}],
                           [{'type': 'RESPONSE', 'content': 'This is the archived DSH badge.'}])
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        if manifest:
            archive.writestr('manifest.json', json.dumps({'export_format_version': version}))
        index = [{'id': cid, 'title': title, 'pinned': False, 'inserted_at': ARCHIVE_TIME,
                  'updated_at': f'2026-11-11T02:00:0{rank}.000Z', 'message_count': 3}
                 for cid, title, rank in [('bad', 'Damaged', 6), ('text', text['title'], 5), ('picture', picture['title'], 4)]]
        archive.writestr('chat_session_index.json', json.dumps(index, ensure_ascii=False))
        archive.writestr(path, png)
        archive.writestr('chat_sessions/bad.json', '{incorrect JSON')
        archive.writestr('chat_sessions/picture.json', json.dumps(picture, ensure_ascii=False))
        archive.writestr('chat_sessions/text.json', json.dumps(text, ensure_ascii=False))
    return buffer.getvalue()


def route(workspace):
    return ROUTE + '?' + urlencode({'workspaceId': workspace})


def connection(emulator):
    url = urlsplit(emulator.url)
    return http.client.HTTPConnection(url.hostname, url.port, timeout=15)


def upload(emulator, workspace, body, authenticated=True, media='application/octet-stream'):
    client = connection(emulator)
    headers = {'Host': HOST_HEADER, 'Content-Type': media}
    if authenticated:
        headers['Cookie'] = emulator.cookie()
    try:
        client.request('POST', route(workspace), body, headers)
        response = client.getresponse()
        data = response.read()
        content_type = response.getheader('content-type', '').split(';', 1)[0]
        lines = [json.loads(row) for row in data.splitlines()] if content_type == 'application/x-ndjson' else []
        return response.status, lines
    finally:
        client.close()


def failure(status, lines, reason):
    assert status == 200 and len(lines) == 1 and lines[0]['type'] == 'outcome', (status, lines)
    outcome = lines[0]['outcome']
    assert not outcome['ok'] and outcome['error']['reason'] == reason, lines
    return outcome['error']


def unfinished_upload(emulator, workspace, evidence):
    client = connection(emulator)
    try:
        client.putrequest('POST', route(workspace), skip_host=True)
        client.putheader('Host', HOST_HEADER)
        client.putheader('Cookie', emulator.cookie())
        client.putheader('Content-Type', 'application/octet-stream')
        client.putheader('Content-Length', '4096')
        client.endheaders(b'PK\x03\x04')
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            status, lines = upload(emulator, workspace, b'not a ZIP')
            if status == 200 and lines and lines[-1]['outcome'].get('error', {}).get('reason') == 'busy':
                evidence['concurrentUploadRejected'] = failure(status, lines, 'busy')
                break
            failure(status, lines, 'unreadable-archive')
            time.sleep(.1)
        else:
            raise AssertionError('The partial upload never held the import slot')
        started = time.monotonic()
        client.sock.shutdown(socket.SHUT_RDWR)
    finally:
        client.close()
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        status, lines = upload(emulator, workspace, b'not a ZIP')
        error = lines[-1]['outcome'].get('error', {}) if lines else {}
        if error.get('reason') != 'busy':
            evidence['postCancelArchiveValidation'] = failure(status, lines, 'unreadable-archive')
            evidence['cancelToSlotReuseMs'] = round((time.monotonic() - started) * 1000)
            return
        time.sleep(.1)
    raise AssertionError('Cancelled upload did not release the import slot')


def bundle(emulator, enabled):
    row, = [row for row in emulator.rpc('pluginManager/listBundles', {}) if row['name'] == BUNDLE]
    assert row['availability'] == 'installation' and row['official'] and row['optional'], row
    assert not row['removable'] and not row.get('error') and row['version'] == '0.2.2-rc.4', row
    assert row['enabled'] == enabled, row
    return {key: row[key] for key in ['availability', 'official', 'optional', 'enabled', 'version']}


def switch(emulator, enabled):
    row = emulator.rpc('pluginManager/setBundleEnabled', {'name': BUNDLE, 'enabled': enabled})
    assert row['application'] in ['applied', 'restart-required'], row
    emulator.stop()
    emulator.start()
    return emulator.ready('normal')


def validate_session(emulator, session, title):
    events = support['events'](emulator, session)
    titles = [row for row in events if row['type'] == 'session/title']
    assert len(titles) == 1 and titles[0]['data'] == {'title': title, 'messageSeqs': [], 'source': {'kind': 'user'}}, titles
    users = [row for row in events if row['type'] == 'user/message']
    assert len(users) == 1
    assert users[0]['time'] == int(datetime.fromisoformat(PROMPT_TIME.replace('Z', '+00:00')).timestamp()*1000), users
    assert [row['time'] for row in events] == sorted(row['time'] for row in events)
    assert 'DISCARDED_BRANCH' not in json.dumps(events)
    return events, users[0]['data']['content']


def validate_import(emulator, sessions, marker, png, evidence):
    text, picture = sessions
    text_events, user_text = validate_session(emulator, text, '导入：存档核对')
    assert user_text == [{'type': 'text', 'text': 'Keep the archive verification code.'}]
    assistant = [block for row in text_events if row['type'] == 'assistant/message' for block in row['data']['message']['content']]
    assert {'type': 'reasoning', 'text': 'Search only the archived export context.'} in assistant, assistant
    assert {'type': 'text', 'text': 'The archive verification code is ' + marker + '.'} in assistant
    call, = [row['data'] for row in text_events if row['type'] == 'tool/call']
    result, = [row['data']['message'] for row in text_events if row['type'] == 'tool/result']
    assert call['name'] == 'web_search' and not result['isError'] and result['toolCallId'] == call['callId']
    assert 'https://example.invalid/fixture' in json.dumps(result)

    picture_events, user_picture = validate_session(emulator, picture, '图片与文件卡片')
    refs = {item['type']: item['attachment'] for item in user_picture if item['type'] in ['image', 'file']}
    assert set(refs) == {'image', 'file'}, user_picture
    attachment = emulator.rpc('session/attachment', {'request': {'sessionId': picture, 'attachment': refs['image']}})
    assert base64.b64decode(attachment['data'], validate=True) == png
    assert refs['image']['mediaType'] == 'image/png' and refs['image']['bytes'] == len(png)
    assert refs['file']['name'] == FILENAMES[1] and refs['file']['bytes'] == 123
    evidence['importedTrace'] = {'text': text_events, 'picture': picture_events}
    evidence['retrievedPngSha256'] = hashlib.sha256(png).hexdigest()
    return text_events


def verify(emulator, path, workspace, evidence, sessions):
    marker = 'IMPORT_' + uuid.uuid4().hex.upper()
    png = SOURCE_PNG.read_bytes()
    archive = archive_bytes(marker, png)
    evidence['export'] = {'bytes': len(archive), 'sha256': hashlib.sha256(archive).hexdigest()}
    assert upload(emulator, workspace, archive)[0] == 404
    evidence['enabledReadyMs'] = switch(emulator, True)
    evidence['enabledCatalog'] = bundle(emulator, True)
    limits = emulator.rpc('deepseekChatImport/limits', {})
    assert limits['maxUploadBytes'] >= len(archive)
    evidence['ownerLimits'] = limits

    assert upload(emulator, workspace, archive, authenticated=False)[0] == 401
    evidence['anonymousUploadDenied'] = True
    assert upload(emulator, workspace, archive, media='text/plain')[0] == 415
    evidence['wrongTypeDenied'] = True
    evidence['missingManifest'] = failure(*upload(emulator, workspace, archive_bytes(marker, png, manifest=False)), 'missing-manifest')
    evidence['unsupportedVersion'] = failure(*upload(emulator, workspace, archive_bytes(marker, png, version=2)), 'unsupported-version')
    unfinished_upload(emulator, workspace, evidence)
    print('Verified upload rejection, busy, cancellation and slot reuse', flush=True)

    status, lines = upload(emulator, workspace, archive)
    assert status == 200 and lines[-1]['type'] == 'outcome' and lines[-1]['outcome']['ok'], (status, lines)
    value = lines[-1]['outcome']['value']
    sessions.extend(value['sessionIds'])
    assert value['workspaceId'] == workspace and value['workspacePath'] == path, value
    assert value['conversationCount'] == 3 and value['omittedByLimit'] == 0
    assert len(sessions) == 2 and len(set(sessions)) == 2 and len(value['skipped']) == 1, value
    assert 'bad' in value['skipped'][0]['conversationId'], value
    assert [row['type'] for row in lines[:-1]] == ['progress'] * 3, lines
    assert [row['done'] for row in lines[:-1]] == [0, 1, 2], lines
    evidence['uploadLines'] = lines
    first = validate_import(emulator, sessions, marker, png, evidence)
    print('Verified restored history, pinned titles and original PNG bytes', flush=True)

    evidence['disabledReadyMs'] = switch(emulator, False)
    evidence['disabledCatalog'] = bundle(emulator, False)
    assert upload(emulator, workspace, archive)[0] == 404
    evidence['uploadRouteRemoved'] = True
    assert support['events'](emulator, sessions[0]) == first
    with support['model_key'](emulator):
        emulator.rpc('session/selectModel', {'request': {'sessionId': sessions[0], **MODEL}})
        calls, _, events = agent['prompt'](emulator, sessions[0],
            'Reply with the archive verification code from earlier in this conversation, exactly as written. Use no tools.')
        assert not calls
        assert events[:len(first)] == first
        assert agent['assistant_texts'](events[len(first):]).strip() == marker
        evidence['continuedModelRecoveredCode'] = True
    evidence['testCredentialRemoved'] = True


def run(emulator, output):
    name = 'mh-chat-import-' + uuid.uuid4().hex[:10]
    path = support['WORKSPACE'] + '/' + name
    folder = 'alpine/workspace-native/' + name
    remote = '/data/local/tmp/' + name
    originals = {}
    workspace = None
    sessions = []
    evidence = {'fixture': name}
    try:
        emulator.ready('normal')
        originals = {file: agent['read_bytes'](emulator, file) for file in [
            PROFILE+'/package.json', PROFILE+'/pnpm-lock.yaml', 'mobile-harness-boot.json',
        ]}
        evidence['initialCatalog'] = bundle(emulator, False)
        emulator.app('mkdir ' + folder)
        registration = emulator.rpc('workspace/create', {'request': {'path': path}})
        workspace = registration['workspace']['workspaceId']
        assert registration['created'], registration
        verify(emulator, path, workspace, evidence, sessions)
        assert agent['read_bytes'](emulator, PROFILE+'/pnpm-lock.yaml') == originals[PROFILE+'/pnpm-lock.yaml']
    finally:
        try:
            if originals:
                for session in sessions:
                    emulator.rpc('workspace/archiveSession', {'request': {'sessionId': session}})
                if workspace is not None:
                    assert emulator.rpc('workspace/delete', {'request': {'workspaceId': workspace}}) == {'deleted': True}
                    evidence['fixtureWorkspaceRemoved'] = True
        finally:
            try:
                if originals:
                    emulator.stop()
                    emulator.app('rm -rf ' + folder)
                    for index, (file, data) in enumerate(originals.items()):
                        lsp['restore_bytes'](emulator, file, data, remote+'-'+str(index))
                    emulator.start()
                    evidence['restoredReadyMs'] = emulator.ready('normal')
                    after = {file: agent['read_bytes'](emulator, file) for file in originals}
                    assert after == originals
                    evidence['restoredConfigurationHashes'] = {file: hashlib.sha256(data).hexdigest() for file, data in after.items()}
            finally:
                output.write_text(json.dumps(evidence, indent=2, ensure_ascii=False)+'\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('target')
    parser.add_argument('output', type=Path)
    options = parser.parse_args()
    if not os.environ.get('MH_TEST_DEEPSEEK_API_KEY'):
        parser.error('MH_TEST_DEEPSEEK_API_KEY is required')
    emulator = support['Emulator'](options.target, 19643)
    forward = ('tcp:19643', 'tcp:19592')
    emulator.hdc('fport', *forward)
    try:
        run(emulator, options.output)
    finally:
        emulator.hdc('fport', 'rm', *forward)
