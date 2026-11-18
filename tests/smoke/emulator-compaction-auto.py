"""Trigger real step-pressure compaction through an isolated copy of the full standard preset."""
import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import runpy
import time
import uuid

manual = runpy.run_path(str(Path(__file__).with_name('emulator-compaction.py')))
agent = manual['agent']; support = manual['support']
lsp = runpy.run_path(str(Path(__file__).with_name('emulator-lsp-lifecycle.py')))
HOME_PATCH = 'alpine/native-benchmark-home/cordis.patch.yml'
POLICY = {'auto': True, 'thresholdRatio': 0.01, 'headroomTokens': 4096,
          'retainTokens': 1, 'maxTokens': 4096, 'compactionRetries': 0}


@contextmanager
def configured_preset(emulator, name, evidence):
    emulator.ready('normal')
    assert emulator.app('test ! -e ' + HOME_PATCH + ' && printf EMPTY') == 'EMPTY'
    roster = emulator.rpc('agentPresets/list', {})
    source = emulator.rpc('agentPresets/read', {'agentPreset': 'standard'})['content']
    evidence['originalStandardPresetSha256'] = hashlib.sha256(source.encode()).hexdigest()
    # Copy every official standard tool, expression and service. Only the
    # compaction policy differs; moving YAML must retain its package resolver.
    root = support['WORKSPACE'].rsplit('/', 1)[0]
    carrier = json.dumps('file://' + root + '/.dsh-0.2.2-rc.5/dsh/package.json')
    copied = source.replace('createRequire(baseUrl)', 'createRequire(' + carrier + ')')
    pattern = r"(?m)^(\s*)name: '@deepseek-ai/dsh-compaction-basic'$"
    def policy_row(match):
        indent = match[1]
        return match[0] + '\n' + indent + 'config:\n' + ''.join(indent + '  ' + key + ': ' + json.dumps(value) + '\n' for key, value in POLICY.items()).rstrip('\n')
    copied, replacements = re.subn(pattern, policy_row, copied)
    assert replacements == 1
    assert re.findall(r'^\s*name: (.+)$', copied, re.M) == re.findall(r'^\s*name: (.+)$', source, re.M)
    evidence['policy'] = POLICY
    evidence['fullOriginalStandardComposition'] = source
    evidence['testPresetComposition'] = copied
    patch = '- insert:\n    - id: ' + name + '\n      name: "@deepseek-ai/dsh-agent-preset"\n      config:\n        id: ' + name + '\n        plugins:\n'
    patch += '\n'.join('          ' + line for line in copied.splitlines()) + '\n'
    emulator.stop()
    try:
        lsp['restore_bytes'](emulator, HOME_PATCH, patch.encode(), '/data/local/tmp/' + name)
        emulator.start(); evidence['configuredReadyMs'] = emulator.ready('normal')
        actual = emulator.rpc('agentPresets/read', {'agentPreset': name})['content']
        assert 'thresholdRatio: 0.01' in actual and 'retainTokens: 1' in actual, actual
        evidence['effectiveTestPresetSha256'] = hashlib.sha256(actual.encode()).hexdigest()
        yield
    finally:
        emulator.stop(); emulator.app('rm -f ' + HOME_PATCH)
        assert emulator.app('test ! -e ' + HOME_PATCH + ' && printf ABSENT') == 'ABSENT'
        emulator.start(); evidence['restoredReadyMs'] = emulator.ready('normal')
        assert emulator.rpc('agentPresets/list', {}) == roster
        assert emulator.rpc('agentPresets/read', {'agentPreset': 'standard'})['content'] == source
        evidence['originalPresetsAndDefaultRestored'] = True


def run(emulator, output):
    name = 'mh-auto-compact-' + uuid.uuid4().hex[:10]
    evidence = {'fixture': name}; sid = None; unfinished = False
    marker = 'AUTO_FACT_' + uuid.uuid4().hex.upper()
    try:
        with configured_preset(emulator, name, evidence):
            with support['model_key'](emulator):
                try:
                    workspace = emulator.rpc('workspace/create', {'request': {'path': support['WORKSPACE']}})['workspace']
                    sid = emulator.rpc('session/create', {'request': {'workspaceId': workspace['workspaceId'], 'agentPreset': name}})['sessionId']
                    evidence['sessionId'] = sid
                    emulator.rpc('session/selectModel', {'request': {'sessionId': sid, 'provider': 'deepseek-official', 'model': 'deepseek-flash', 'reasoningEffort': 'off'}})
                    filler = '\n'.join(f'Archived sample {index}: checksum {hashlib.sha256(str(index).encode()).hexdigest()}, all measurements complete, nothing to execute.' for index in range(230))
                    unfinished = True
                    calls, _, _ = agent['prompt'](emulator, sid,
                        'Keep this exact essential pending decision label for later recall: ' + marker
                        + '. Do not write it to disk or call any tools. Archived samples below are disposable completed observations. '
                        'Acknowledge in one brief sentence only.\n<archive>\n' + filler + '\n</archive>')
                    assert not calls; unfinished = False
                    before = support['events'](emulator, sid); cutoff = before[-1]['seq']
                    assert not any(row['type'] == 'compaction/summary' for row in before)
                    unfinished = True; started = time.monotonic()
                    calls, _, after = agent['prompt'](emulator, sid,
                        'Recall the exact essential pending decision label from our earlier conversation. '
                        'Reply only with that label. No tools, disk reads, or questions.')
                    unfinished = False; assert not calls
                    reply = agent['assistant_texts']([row for row in after if row['seq'] > cutoff]).strip()
                    assert reply == marker, reply
                    summaries = [row for row in after if row['type'] == 'compaction/summary' and row['seq'] > cutoff]
                    assert len(summaries) == 1, summaries
                    summary = summaries[0]; data = summary['data']
                    assert 'sourceCommandId' not in data and data['llmStreamCall'] is True
                    assert data['provider'] == 'deepseek-official' and data['model'] == 'deepseek-flash'
                    assert data['usage']['outputTokens'] > 0
                    first = [row for row in after if row['type'] == 'compaction/start' and row['data']['compactionId'] == data['compactionId']]
                    last = [row for row in after if row['type'] == 'compaction/end' and row['data']['compactionId'] == data['compactionId']]
                    assert len(first) == len(last) == 1
                    assert isinstance(first[0]['data']['turn'], int) and first[0]['data']['turn'] == last[0]['data']['turn']
                    assert not last[0]['data'].get('error')
                    assert not any(row['type'] == 'command/run' for row in after)
                    current = {row['seq']: row for row in after}
                    assert all(current[row['seq']] == row for row in before)
                    checkpoints = [row for row in after if row['type'] == 'user/message' and row['data'].get('source', {}).get('compactionId') == data['compactionId']]
                    assert len(checkpoints) == 1
                    text = ''.join(block.get('text', '') for block in checkpoints[0]['data']['content'])
                    assert marker in text and len(text) < len(filler) // 2
                    evidence['automatic'] = {'start': first[0], 'summary': summary, 'end': last[0],
                                             'checkpoint': checkpoints[0], 'exactRecall': reply,
                                             'turnElapsedMs': round((time.monotonic() - started) * 1000),
                                             'noCompactCommandInvoked': True, 'originalLogPreserved': True}
                    print('automatic pressure compaction passed', flush=True)
                finally:
                    if sid and unfinished: emulator.rpc('session/cancel', {'request': {'sessionId': sid}})
                    if sid: emulator.rpc('workspace/archiveSession', {'request': {'sessionId': sid}})
            evidence['temporaryModelCredentialRemoved'] = True
    finally: output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + '\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('target'); parser.add_argument('output', type=Path); options = parser.parse_args()
    if not os.environ.get('MH_TEST_DEEPSEEK_API_KEY'): parser.error('MH_TEST_DEEPSEEK_API_KEY is required')
    emulator = support['Emulator'](options.target, 19643); forward = ('tcp:19643', 'tcp:19592')
    emulator.hdc('fport', *forward)
    try: run(emulator, options.output)
    finally: emulator.hdc('fport', 'rm', *forward)
