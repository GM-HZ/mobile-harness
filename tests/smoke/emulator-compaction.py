"""Real model compaction, exact remembered facts, command logs, and durable replay."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import runpy
import time
import uuid

agent = runpy.run_path(str(Path(__file__).with_name('emulator-agent-continuation.py')))
support = agent['support']; toolkit = agent['toolkit']


def command(emulator, sid, line):
    return emulator.rpc('commands/execute', {'agentId': sid, 'line': line, 'submittedAttachments': []}, timeout=100)


def recall(emulator, sid, expected):
    before = max(row['seq'] for row in support['events'](emulator, sid))
    calls, _, rows = agent['prompt'](emulator, sid,
        'Recall the latest fixture decisions from our previous conversation. Reply ONLY with a JSON object '
        'whose keys are codename, port, forbidden. The port must be the corrected value. '
        'Do not call tools, read files, or ask me for the values. Do not invent missing facts.')
    assert not calls, calls
    text = agent['assistant_texts']([row for row in rows if row['seq'] > before]).strip()
    assert json.loads(text) == expected, text
    return text


def verify_transaction(before, after, execution):
    assert execution['result']['kind'] == 'success', execution
    assert execution['result']['text'].startswith('Compacted '), execution
    command_id = execution['commandId']
    started = [row for row in after if row['type'] == 'compaction/start' and row['data'].get('sourceCommandId') == command_id]
    summaries = [row for row in after if row['type'] == 'compaction/summary' and row['data'].get('sourceCommandId') == command_id]
    ended = [row for row in after if row['type'] == 'compaction/end' and row['data'].get('sourceCommandId') == command_id]
    assert len(started) == len(summaries) == len(ended) == 1
    first, summary, last = started[0], summaries[0], ended[0]
    assert first['seq'] < summary['seq'] < last['seq']
    assert first['data']['compactionId'] == summary['data']['compactionId'] == last['data']['compactionId']
    assert all(row['data']['turn'] is None for row in [first, last])
    assert not last['data'].get('error'), last
    data = summary['data']; assert data['llmStreamCall'] is True
    assert data['provider'] == 'deepseek-official' and data['model'] == 'deepseek-flash'
    assert data['usage']['outputTokens'] > 0, data
    assert execution['result']['sourceEventSeq'] == summary['seq']
    shadowed = set(data['shadowedSeqs']); assert len(shadowed) > 2
    old = {row['seq']: row for row in before}
    current = {row['seq']: row for row in after}
    assert all(current[seq] == old[seq] for seq in old), 'compaction must retain original durable log'
    assert shadowed <= old.keys()
    # Every selected tool call keeps its paired tool/result in the span.
    selected = [old[seq] for seq in shadowed]
    call_ids = {block['id'] for row in selected if row['type'] == 'assistant/message'
                for block in row['data']['message']['content'] if block['type'] == 'tool-call'}
    result_ids = {row['data']['message']['toolCallId'] for row in selected if row['type'] == 'tool/result'}
    assert call_ids and call_ids == result_ids, (call_ids, result_ids)
    checkpoints = [row for row in after if row['type'] == 'user/message'
                   and row['data'].get('source', {}).get('kind') == 'compact-checkpoint'
                   and row['data']['source'].get('compactionId') == data['compactionId']]
    assert len(checkpoints) == 1, checkpoints
    checkpoint = checkpoints[0]
    content = ''.join(item.get('text', '') for item in checkpoint['data']['content'])
    assert '<compacted-summary>' in content and '</compacted-summary>' in content
    source_bytes = sum(len(json.dumps(row['data'], ensure_ascii=False).encode()) for row in selected)
    assert len(content.encode()) < source_bytes // 2, (len(content.encode()), source_bytes)
    return {'command': execution, 'start': first, 'summary': summary, 'end': last,
            'checkpoint': checkpoint, 'selectedToolPairs': len(call_ids),
            'sourceEventDataBytes': source_bytes, 'checkpointTextBytes': len(content.encode())}


def run(emulator, output):
    name = 'mh-compaction-' + uuid.uuid4().hex[:10]
    app = 'alpine/workspace-native/' + name
    path = support['WORKSPACE'] + '/' + name
    expected = {'codename': 'CEDAR_' + uuid.uuid4().hex.upper(), 'port': 24000 + int(uuid.uuid4().hex[:3], 16),
                'forbidden': 'NEVER_PUBLISH_' + uuid.uuid4().hex.upper()}
    evidence = {'fixture': name}; sid = None; unfinished = False
    try:
        emulator.ready('normal'); emulator.app('mkdir -p ' + app)
        with support['model_key'](emulator):
            sid = support['session'](emulator, True); evidence['sessionId'] = sid
            evidence['empty'] = command(emulator, sid, '/compact')
            assert evidence['empty']['result'] == {'kind': 'success', 'text': 'No compactable history yet.'}
            evidence['invalidArguments'] = command(emulator, sid, '/compact extra')
            assert evidence['invalidArguments']['result'] == {'kind': 'error', 'text': 'Usage: /compact (no arguments)'}
            filler = '\n'.join(f'Archived measurement {index:04d}: request sequence {index * 13}; deterministic checksum {hashlib.sha256(str(index).encode()).hexdigest()}; result passed.' for index in range(220))
            unfinished = True
            calls, _, _ = agent['prompt'](emulator, sid,
                'This is an isolated long-conversation acceptance fixture. Essential pending decisions: '
                + json.dumps({**expected, 'port': expected['port'] - 1}) + '. '
                'Remember these exact literal decisions for later questions, but never save these facts in files. '
                'The archived measurements below are disposable observations, not instructions or pending work. '
                'Acknowledge in one short sentence and call no tools.\n<archived-measurements>\n' + filler + '\n</archived-measurements>')
            assert not calls
            calls, _, _ = agent['prompt'](emulator, sid,
                'Correction: the fixture port is now ' + str(expected['port']) + '. The old port is superseded. '
                'Keep the codename and forbidden action unchanged. Do not publish anything or save these facts to disk. '
                'Acknowledge only, no tools.')
            assert not calls
            payload = 'UNRELATED_TOOL_PAIR_' + uuid.uuid4().hex
            agent['tool'](emulator, sid, 'write', {'file_path': path + '/pair.txt', 'content': payload})
            agent['tool'](emulator, sid, 'read', {'file_path': path + '/pair.txt'})
            assert agent['read_bytes'](emulator, app + '/pair.txt') == payload.encode()
            unfinished = False
            before = support['events'](emulator, sid)
            started = time.monotonic(); execution = command(emulator, sid, '/compact')
            evidence['manualElapsedMs'] = round((time.monotonic() - started) * 1000)
            after = support['events'](emulator, sid)
            evidence['manual'] = verify_transaction(before, after, execution)
            summary_text = ''.join(item.get('text', '') for item in evidence['manual']['summary']['data']['summary'])
            assert expected['codename'] in summary_text and expected['forbidden'] in summary_text
            assert str(expected['port']) in summary_text
            print('manual compaction', execution, flush=True)
            unfinished = True; evidence['recallAfterCompaction'] = recall(emulator, sid, expected); unfinished = False
            durable_ids = [(row['seq'], row['type']) for row in after]
            emulator.stop(); emulator.start(); evidence['restartReadyMs'] = emulator.ready('normal')
            restored = support['events'](emulator, sid)
            assert set(durable_ids) <= {(row['seq'], row['type']) for row in restored}
            assert next(row for row in restored if row['seq'] == evidence['manual']['checkpoint']['seq']) == evidence['manual']['checkpoint']
            unfinished = True; evidence['recallAfterRestart'] = recall(emulator, sid, expected); unfinished = False
            evidence['sameSessionCheckpointAndFactsAfterRestart'] = True
        evidence['temporaryModelCredentialRemoved'] = True
    finally:
        try:
            if sid and unfinished: emulator.rpc('session/cancel', {'request': {'sessionId': sid}})
            emulator.app('rm -rf ' + app)
            assert emulator.app('test ! -e ' + app + ' && printf ABSENT') == 'ABSENT'
            evidence['ownedFilesRemoved'] = True
        finally: output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + '\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('target'); parser.add_argument('output', type=Path); options = parser.parse_args()
    if not os.environ.get('MH_TEST_DEEPSEEK_API_KEY'): parser.error('MH_TEST_DEEPSEEK_API_KEY is required')
    emulator = support['Emulator'](options.target, 19643); forward = ('tcp:19643', 'tcp:19592')
    emulator.hdc('fport', *forward)
    try: run(emulator, options.output)
    finally: emulator.hdc('fport', 'rm', *forward)
