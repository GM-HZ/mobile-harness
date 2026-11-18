"""Trigger real Messages overflow, compaction, retry, and restart recall on the shipped Host."""

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import re
import runpy
import time
import uuid
import zipfile

importer = runpy.run_path(str(Path(__file__).with_name('emulator-chat-import.py')))
agent, support, lsp = (importer[key] for key in ('agent', 'support', 'lsp'))
MODEL = importer['MODEL']
ARCHIVE_REPEATS = 340_000
PROMPT_REPEATS = 195_000


def owned_archive(name, marker):
    stamp = importer['ARCHIVE_TIME']
    messages = [
        {'id': 1, 'parent_id': None, 'role': 'USER', 'status': 'FINISHED',
         'inserted_at': stamp, 'fragments': [{'type': 'REQUEST', 'content':
             'Keep this exact pending decision label for future recall: ' + marker
             + '. Ignore this completed synthetic ledger of numeric IDs:' + ' 9' * ARCHIVE_REPEATS}]},
        {'id': 2, 'parent_id': 1, 'role': 'ASSISTANT', 'status': 'FINISHED',
         'inserted_at': stamp, 'fragments': [{'type': 'RESPONSE', 'content':
             'The exact pending decision label is ' + marker + '. The synthetic ledger can be forgotten.'}]},
    ]
    session = {'id': name, 'title': name, 'inserted_at': stamp, 'messages': messages, 'current_message_id': 2}
    index = [{'id': name, 'title': name, 'pinned': False, 'inserted_at': stamp, 'updated_at': stamp, 'message_count': 2}]
    data = io.BytesIO()
    with zipfile.ZipFile(data, 'w', compression=zipfile.ZIP_STORED) as archive:
        archive.writestr('manifest.json', '{"export_format_version":3}')
        archive.writestr('chat_session_index.json', json.dumps(index))
        archive.writestr(f'chat_sessions/{name}.json', json.dumps(session))
    return data.getvalue()


def wait_turn(device, session, cutoff):
    deadline = time.monotonic() + 320
    while time.monotonic() < deadline:
        result = device.rpc('session/wait', {'request': {'sessionId': session, 'timeoutMs': 10_000,
                            'afterSeq': cutoff, 'maxMessages': 4}}, timeout=20)
        if result['reason'] == 'idle' and result['state']['cursor'] > cutoff:
            after = [row for row in support['events'](device, session) if row['seq'] > cutoff]
            if any(row['type'] == 'turn/end' for row in after):
                return after
        if result['reason'] == 'input-required':
            raise AssertionError('The text-only overflow test unexpectedly requires input')
        time.sleep(.4)
    raise AssertionError('The real overflow turn exceeded its observation budget')


def failures(value):
    if isinstance(value, dict):
        if value.get('code') == 'CONTEXT_WINDOW_EXCEEDED':
            yield value
        for child in value.values():
            yield from failures(child)
    elif isinstance(value, list):
        for child in value:
            yield from failures(child)


def verify_turn(device, session, marker, evidence):
    before = support['events'](device, session)
    assert marker in agent['assistant_texts'](before)
    cutoff = before[-1]['seq']
    request = (
        'Recall the exact pending decision label from the earlier archive and reply only with that label. '
        'Use no tools. Ignore all closed synthetic IDs in this message.'
        + ' 9' * PROMPT_REPEATS + '\nReturn only the earlier pending decision label.'
    )
    started = time.monotonic()
    device.rpc('session/prompt', {'request': {'sessionId': session, 'requestId': str(uuid.uuid4()),
               'mode': 'queue', 'content': [{'type': 'text', 'text': request}]}}, timeout=45)
    rows = wait_turn(device, session, cutoff)
    evidence['liveTurnMs'] = round((time.monotonic() - started) * 1000)
    evidence['turnEventTypes'] = [row['type'] for row in rows]
    attempts = [row for row in rows if row['type'] == 'assistant/attempt']
    error_rows = [(row['seq'], failure) for row in attempts for failure in failures(row['data'])]
    assert len(error_rows) == 1, evidence['turnEventTypes']
    error_seq, failure = error_rows[0]
    message = failure['message']
    limit = re.search(r'maximum context length is (\d+) tokens.*requested (\d+) tokens', message, re.I)
    assert failure['status'] == 400 and limit, failure.get('code')
    limit_tokens, counted = map(int, limit.groups())
    assert counted > limit_tokens
    evidence['publicOverflow'] = {'status': 400, 'code': failure['code'], 'limitTokens': limit_tokens,
                                  'requestedTokens': counted, 'requestIdPresent': bool(failure.get('requestId'))}
    compaction = [row for row in rows if row['type'].startswith('compaction/')]
    evidence['compactionErrors'] = [
        re.sub(r' \(request_id: [^)]+\)$', '', row['data']['error'])
        for row in compaction if row['data'].get('error')
    ]
    assert [row['type'] for row in compaction] == ['compaction/start', 'compaction/summary', 'compaction/end']
    assert error_seq < compaction[0]['seq']
    summary = compaction[1]['data']
    assert summary['model'] == MODEL['model'] and summary['provider'] == MODEL['provider']
    assert summary['llmStreamCall'] is True and summary['usage']['outputTokens'] > 0
    assert not compaction[-1]['data'].get('error')
    evidence['summaryInputTokens'] = summary['usage'].get('inputTokens')
    evidence['summaryOutputTokens'] = summary['usage']['outputTokens']
    starts = [row for row in rows if row['type'] == 'turn/start']
    ends = [row for row in rows if row['type'] == 'turn/end']
    assert len(starts) == len(ends) == 1
    assert max(summary['shadowedSeqs']) < starts[0]['seq']
    evidence['shadowedOnlyPriorTurn'] = True
    evidence['turnReason'] = ends[0]['data']['reason']
    assert ends[0]['data']['reason']['kind'] == 'completed'
    assert not any(row['type'] == 'tool/call' for row in rows)
    reply = agent['assistant_texts'](rows).strip()
    assert reply == marker, 'The retry did not restore the exact earlier label'
    current = {row['seq']: row for row in support['events'](device, session)}
    assert all(current[row['seq']] == row for row in before)
    evidence['sameTurnExactReply'] = True
    evidence['originalArchiveHistoryPreserved'] = True
    device.stop()
    device.start()
    evidence['restartReadyMs'] = device.ready('normal')
    before = support['events'](device, session)
    boundary = before[-1]['seq']
    calls, _, after = agent['prompt'](device, session,
        'Recall the exact pending decision label from this conversation. Reply with that label only. Do not call tools.',
        timeout=95)
    assert not calls
    assert agent['assistant_texts']([row for row in after if row['seq'] > boundary]).strip() == marker
    evidence['exactRecallAfterRestart'] = True


def run(device, output):
    name = 'mh-live-overflow-' + uuid.uuid4().hex[:10]
    marker = 'PENDING_' + uuid.uuid4().hex.upper()
    folder = 'alpine/workspace-native/' + name
    bridge = ('tcp:19643', 'tcp:19592')
    session = workspace = None
    originals = {}
    evidence = {'archiveRepeats': ARCHIVE_REPEATS, 'promptRepeats': PROMPT_REPEATS}
    assert 'Forwardport result:OK' in device.hdc('fport', *bridge)
    try:
        device.ready('normal')
        importer['bundle'](device, False)
        files = [importer['PROFILE'] + '/' + leaf for leaf in ('package.json', 'pnpm-lock.yaml', 'cordis.patch.yml')]
        originals = {file: agent['read_bytes'](device, file) for file in files + ['mobile-harness-boot.json']}
        importer['switch'](device, True)
        device.app('mkdir ' + folder)
        path = support['WORKSPACE'] + '/' + name
        workspace = device.rpc('workspace/create', {'request': {'path': path}})['workspace']['workspaceId']
        archive = owned_archive(name, marker)
        evidence['archiveBytes'] = len(archive)
        status, lines = importer['upload'](device, workspace, archive)
        assert status == 200 and lines[-1]['outcome']['ok'], (status, lines)
        session, = lines[-1]['outcome']['value']['sessionIds']
        evidence['fixtureSessionId'] = session
        with support['model_key'](device):
            device.rpc('session/selectModel', {'request': {'sessionId': session, **MODEL}})
            verify_turn(device, session, marker, evidence)
        evidence['testCredentialRemoved'] = True
    finally:
        try:
            try:
                if session:
                    device.rpc('session/cancel', {'request': {'sessionId': session}})
                    device.rpc('workspace/archiveSession', {'request': {'sessionId': session}})
                if workspace:
                    assert device.rpc('workspace/delete', {'request': {'workspaceId': workspace}}) == {'deleted': True}
            finally:
                if originals:
                    device.stop()
                    device.app('rm -rf ' + folder)
                    for index, (file, contents) in enumerate(originals.items()):
                        lsp['restore_bytes'](device, file, contents, '/data/local/tmp/' + name + str(index))
                    device.start()
                    device.ready('normal')
                    assert all(agent['read_bytes'](device, file) == contents for file, contents in originals.items())
                    evidence['restoredProfileHashes'] = {
                        file: hashlib.sha256(contents).hexdigest() for file, contents in originals.items()
                    }
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
