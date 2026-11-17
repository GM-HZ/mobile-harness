"""Real model-facing TypeScript LSP navigation through the packaged phone server."""
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
support = agent['support']; toolkit = agent['toolkit']

SHAPES = '\n'.join([
    'export interface Shape {', '  area(): number', '}', '',
    'export class Circle implements Shape {', '  constructor(private r: number) {}',
    '  area(): number { return Math.PI * this.r * this.r }', '}', '',
    'export function describe(s: Shape): string {', '  return `area=${s.area()}`', '}', '',
])
CONSUMER = '\n'.join([
    "import { Circle, describe } from './shapes.js';",
    'export const answer = describe(new Circle(2));',
    'export const constant = Math.PI;',
    'const compass = "🧭"; export const result = describe(new Circle(3));', '',
])


def at(operation, file, text, line, symbol):
    prefix = text.splitlines()[line - 1].split(symbol, 1)[0]
    return {'operation': operation, 'file_path': file, 'line': line,
            'character': len(prefix.encode('utf-16-le')) // 2 + 2}


def traces(emulator):
    return [json.loads(line) for line in emulator.app('cat alpine/tmp/dsh-native-timeline.log').splitlines()]


def live_helpers(emulator):
    rows = traces(emulator)
    state = {}
    for row in rows:
        if row['event'] in {'host-subprocess-started', 'host-subprocess-reaped'}:
            state[row['pid']] = row['event']
    return {pid for pid, last in state.items() if last == 'host-subprocess-started'}


def query(emulator, sid, args, evidence, key, expect_error=False):
    started = time.monotonic()
    result, rows = agent['tool'](emulator, sid, 'lsp', args, expect_error=expect_error)
    text = toolkit['texts']([result])
    evidence[key] = {'args': args, 'text': text, 'elapsedMs': round((time.monotonic() - started) * 1000), 'isError': expect_error}
    print(key, json.dumps(evidence[key], ensure_ascii=False), flush=True)
    return text


def run(emulator, output):
    name = 'mh-lsp-' + uuid.uuid4().hex[:10]
    path = support['WORKSPACE'] + '/' + name
    app = 'alpine/workspace-native/' + name
    outside = 'alpine/workspace-native/' + name + '-outside.ts'
    evidence = {'fixture': name}; sid = None; created = False
    try:
        emulator.ready('normal')
        root = support['WORKSPACE'].rsplit('/', 1)[0]
        evidence['installedVersions'] = {}
        for package in ['@deepseek-ai/dsh-lsp', '@deepseek-ai/dsh-lsp-stdio', '@deepseek-ai/dsh-tool-lsp', 'typescript', 'typescript-language-server']:
            data = json.loads(emulator.app('cat alpine/.dsh-0.2.2-rc.4/dsh/node_modules/' + package + '/package.json'))
            evidence['installedVersions'][package] = data['version']
        assert evidence['installedVersions'] == {'@deepseek-ai/dsh-lsp': '0.2.2-rc.4', '@deepseek-ai/dsh-lsp-stdio': '0.2.2-rc.4', '@deepseek-ai/dsh-tool-lsp': '0.2.2-rc.4', 'typescript': '6.0.3', 'typescript-language-server': '5.0.0'}
        evidence['noServerBeforeFirstQuery'] = not live_helpers(emulator)
        assert evidence['noServerBeforeFirstQuery']
        emulator.app('mkdir -p ' + app); created = True
        emulator.app("printf '// BOUNDARY_SENTINEL' > " + outside)
        with support['model_key'](emulator):
            sid = support['session'](emulator, True); evidence['sessionId'] = sid
            agent['tool'](emulator, sid, 'working_directory', {'cd': path})
            for file, content in [('shapes.ts', SHAPES), ('consumer.ts', CONSUMER),
                                  ('empty.ts', '// no symbol here\n'),
                                  ('tsconfig.json', json.dumps({'compilerOptions': {'strict': True, 'module': 'nodenext', 'target': 'es2022', 'types': [], 'skipLibCheck': True}}))]:
                agent['tool'](emulator, sid, 'write', {'file_path': file, 'content': content})
                assert agent['read_bytes'](emulator, app + '/' + file) == content.encode()
            text = query(emulator, sid, at('goToDefinition', 'consumer.ts', CONSUMER, 2, 'describe'), evidence, 'definition')
            assert text == 'shapes.ts:10:17', text
            pooled = live_helpers(emulator); assert len(pooled) == 1, pooled
            evidence['pooledServerPid'] = next(iter(pooled))
            text = query(emulator, sid, at('findReferences', 'shapes.ts', SHAPES, 10, 'describe'), evidence, 'references')
            expected = {'shapes.ts:10:17', 'consumer.ts:1:18', 'consumer.ts:2:23'}
            # The import starts at column18 (Circle at10, comma+space at16).
            assert expected <= set(text.splitlines()), (expected, text)
            text = query(emulator, sid, at('goToImplementation', 'shapes.ts', SHAPES, 1, 'Shape'), evidence, 'implementation')
            assert text == 'shapes.ts:5:14', text
            text = query(emulator, sid, at('hover', 'consumer.ts', CONSUMER, 2, 'Circle'), evidence, 'hover')
            assert 'Circle' in text and 'number' in text, text
            text = query(emulator, sid, at('goToDefinition', 'consumer.ts', CONSUMER, 4, 'describe'), evidence, 'utf16AfterAstralCharacter')
            assert text == 'shapes.ts:10:17', text
            text = query(emulator, sid, at('goToDefinition', 'consumer.ts', CONSUMER, 3, 'PI'), evidence, 'standardLibrary')
            assert root + '/.dsh-0.2.2-rc.4/dsh/node_modules/typescript/lib/lib.es5.d.ts:' in text, text
            for line in text.splitlines():
                file, number, column = line.rsplit(':', 2)
                assert file.startswith(root + '/'), line
                source = agent['read_bytes'](emulator, 'alpine/' + file[len(root) + 1:]).decode().splitlines()
                assert 'PI' in source[int(number) - 1], line
            fresh = CONSUMER + 'export const rewritten: boolean = true;\n'
            agent['tool'](emulator, sid, 'write', {'file_path': 'consumer.ts', 'content': fresh})
            text = query(emulator, sid, at('hover', 'consumer.ts', fresh, len(fresh.splitlines()), 'rewritten'), evidence, 'freshSource')
            assert 'rewritten' in text and 'boolean' in text, text
            text = query(emulator, sid, {'operation': 'goToDefinition', 'file_path': 'empty.ts', 'line': 1, 'character': 1}, evidence, 'noResult')
            assert text == 'No results.', text
            text = query(emulator, sid, {'operation': 'hover', 'file_path': support['WORKSPACE'] + '/' + name + '-outside.ts', 'line': 1, 'character': 1}, evidence, 'outsideWorkspace', True)
            assert 'outside the workspace' in text and 'BOUNDARY_SENTINEL' not in text, text
            assert live_helpers(emulator) == pooled, (pooled, live_helpers(emulator))
            evidence['sameServerReusedAcrossQueries'] = True
            pid = next(iter(pooled))
            assert emulator.app(f'kill -9 {pid} && printf KILLED') == 'KILLED'
            text = query(emulator, sid, at('hover', 'consumer.ts', fresh, len(fresh.splitlines()), 'rewritten'), evidence, 'afterServerCrash')
            assert 'rewritten' in text and 'boolean' in text, text
            replaced = live_helpers(emulator); assert len(replaced) == 1 and pid not in replaced, replaced
            assert any(r['event'] == 'host-subprocess-reaped' and r['pid'] == pid for r in traces(emulator))
            evidence['crashedServerReplacedAndReaped'] = True
            sid = None  # The exact model turns are completed; no outstanding request.
        evidence['temporaryModelCredentialRemoved'] = True
    finally:
        try:
            try:
                if sid: emulator.rpc('session/cancel', {'request': {'sessionId': sid}})
            finally:
                if created:
                    emulator.stop(); emulator.app('rm -rf ' + app + '; rm -f ' + outside); emulator.start()
                    evidence['finalNormalReadyMs'] = emulator.ready('normal')
        finally: output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + '\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('target'); parser.add_argument('output', type=Path); options = parser.parse_args()
    if not os.environ.get('MH_TEST_DEEPSEEK_API_KEY'): parser.error('MH_TEST_DEEPSEEK_API_KEY is required')
    emulator = support['Emulator'](options.target, 19643); forward = ('tcp:19643', 'tcp:19592'); emulator.hdc('fport', *forward)
    try: run(emulator, options.output)
    finally: emulator.hdc('fport', 'rm', *forward)
