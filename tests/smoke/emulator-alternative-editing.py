"""Exercise official string editor and multi-file patch tools with real model calls."""
import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import runpy
import uuid

agent = runpy.run_path(str(Path(__file__).with_name('emulator-agent-continuation.py')))
support = agent['support']; toolkit = agent['toolkit']
lsp = runpy.run_path(str(Path(__file__).with_name('emulator-lsp-lifecycle.py')))
HOME_PATCH = 'alpine/native-benchmark-home/cordis.patch.yml'
PATCH = '''- insert:
    - id: mh-test-string-editor
      name: '@deepseek-ai/dsh-tool-str-replace-editor'
      config:
        maxOutputChars: 1024
    - id: mh-test-apply-patch
      name: '@deepseek-ai/dsh-tool-fs'
      config:
        read: false
        readImage: false
        write: false
        edit: false
        applyPatch: true
'''


@contextmanager
def configured_tools(emulator, evidence):
    emulator.ready('normal')
    assert emulator.app('test ! -e ' + HOME_PATCH + ' && printf EMPTY') == 'EMPTY'
    emulator.stop()
    try:
        lsp['restore_bytes'](emulator, HOME_PATCH, PATCH.encode(), '/data/local/tmp/mh-edit-tools-' + uuid.uuid4().hex)
        emulator.start(); evidence['configuredReadyMs'] = emulator.ready('normal')
        yield
    finally:
        emulator.stop(); emulator.app('rm -f ' + HOME_PATCH)
        assert emulator.app('test ! -e ' + HOME_PATCH + ' && printf ABSENT') == 'ABSENT'
        emulator.start(); evidence['restoredReadyMs'] = emulator.ready('normal')
        evidence['temporaryToolConfigurationRemoved'] = True


def invoke(emulator, sid, evidence, key, tool, args, error=False):
    result, rows = agent['tool'](emulator, sid, tool, args, expect_error=error)
    text = toolkit['texts']([result])
    evidence[key] = {'tool': tool, 'args': args, 'text': text, 'isError': error}
    print(key, 'rejected' if error else 'returned', flush=True)
    return text, rows


def run(emulator, output):
    name = 'mh-alt-edit-' + uuid.uuid4().hex[:10]
    app = 'alpine/workspace-native/' + name; path = support['WORKSPACE'] + '/' + name
    outside = 'alpine/' + name + '-outside'
    outside_path = support['WORKSPACE'].rsplit('/', 1)[0] + '/' + name + '-outside'
    evidence = {'fixture': name}; sid = None; unfinished = False
    try:
        emulator.app('mkdir -p ' + app + ' ' + outside)
        lsp['restore_bytes'](emulator, outside + '/protected.txt', b'OUTSIDE_UNCHANGED\n', '/data/local/tmp/' + name)
        with configured_tools(emulator, evidence):
            with support['model_key'](emulator):
                try:
                    sid = support['session'](emulator, True); evidence['sessionId'] = sid; unfinished = True
                    agent['tool'](emulator, sid, 'working_directory', {'cd': path})
                    file = path + '/editor.txt'
                    content = '标题 🧭\nalpha=1\nrepeat\nrepeat\nlast\n'
                    invoke(emulator, sid, evidence, 'create', 'str_replace_editor', {'command': 'create', 'path': file, 'file_text': content})
                    assert agent['read_bytes'](emulator, app + '/editor.txt') == content.encode()
                    text, _ = invoke(emulator, sid, evidence, 'viewRange', 'str_replace_editor', {'command': 'view', 'path': file, 'view_range': [2, 3]})
                    assert 'alpha=1' in text and '标题' not in text and 'last' not in text
                    text, _ = invoke(emulator, sid, evidence, 'createCannotOverwrite', 'str_replace_editor', {'command': 'create', 'path': file, 'file_text': 'MUST_NOT_OVERWRITE'}, True)
                    assert 'already exists' in text.lower()
                    assert agent['read_bytes'](emulator, app + '/editor.txt') == content.encode()
                    invoke(emulator, sid, evidence, 'uniqueReplace', 'str_replace_editor', {'command': 'str_replace', 'path': file, 'old_str': 'alpha=1', 'new_str': 'alpha=2'})
                    content = content.replace('alpha=1', 'alpha=2'); assert agent['read_bytes'](emulator, app + '/editor.txt') == content.encode()
                    text, _ = invoke(emulator, sid, evidence, 'ambiguousReplaceRefused', 'str_replace_editor', {'command': 'str_replace', 'path': file, 'old_str': 'repeat', 'new_str': 'MUST_NOT_REPLACE'}, True)
                    assert 'multiple occurrences' in text.lower()
                    assert agent['read_bytes'](emulator, app + '/editor.txt') == content.encode()
                    invoke(emulator, sid, evidence, 'insert', 'str_replace_editor', {'command': 'insert', 'path': file, 'insert_line': 2, 'new_str': 'INSERTED'})
                    content = content.replace('alpha=2\n', 'alpha=2\nINSERTED\n'); assert agent['read_bytes'](emulator, app + '/editor.txt') == content.encode()
                    invoke(emulator, sid, evidence, 'replaceWithOmittedNewStrDeletes', 'str_replace_editor', {'command': 'str_replace', 'path': file, 'old_str': 'INSERTED\n'})
                    content = content.replace('INSERTED\n', ''); assert agent['read_bytes'](emulator, app + '/editor.txt') == content.encode()
                    text, _ = invoke(emulator, sid, evidence, 'observeOwnedOutsideFile', 'str_replace_editor', {'command': 'view', 'path': outside_path + '/protected.txt'})
                    assert 'OUTSIDE_UNCHANGED' in text
                    text, _ = invoke(emulator, sid, evidence, 'editorOutsideRefused', 'str_replace_editor', {'command': 'str_replace', 'path': outside_path + '/protected.txt', 'old_str': 'OUTSIDE_UNCHANGED', 'new_str': 'MUST_NOT_CHANGE'}, True)
                    assert 'sandbox' in text.lower()
                    assert agent['read_bytes'](emulator, outside + '/protected.txt') == b'OUTSIDE_UNCHANGED\n'
                    patch = '*** Begin Patch\n*** Add File: alpha.txt\n+one\n+two\n*** Add File: delete.txt\n+delete me\n*** End Patch'
                    text, _ = invoke(emulator, sid, evidence, 'patchCreatesTwoFiles', 'apply_patch', {'input': patch})
                    assert text.startswith('Success.')
                    assert agent['read_bytes'](emulator, app + '/alpha.txt') == b'one\ntwo\n'
                    assert agent['read_bytes'](emulator, app + '/delete.txt') == b'delete me\n'
                    patch = '*** Begin Patch\n*** Update File: alpha.txt\n@@\n one\n-two\n+changed\n*** Update File: editor.txt\n@@\n-MISSING_HUNK_MUST_REFUSE\n+bad\n*** End Patch'
                    text, _ = invoke(emulator, sid, evidence, 'preflightFailureChangesNothing', 'apply_patch', {'input': patch}, True)
                    assert 'MISSING_HUNK_MUST_REFUSE' in text
                    assert agent['read_bytes'](emulator, app + '/alpha.txt') == b'one\ntwo\n'
                    assert agent['read_bytes'](emulator, app + '/editor.txt') == content.encode()
                    patch = '*** Begin Patch\n*** Update File: alpha.txt\n*** Move to: moved.txt\n@@\n one\n-two\n+changed\n*** Delete File: delete.txt\n*** End Patch'
                    text, _ = invoke(emulator, sid, evidence, 'patchMoveUpdateAndDelete', 'apply_patch', {'input': patch})
                    assert text.startswith('Success.'), text
                    assert agent['read_bytes'](emulator, app + '/moved.txt') == b'one\nchanged\n'
                    assert emulator.app('test ! -e ' + app + '/alpha.txt && test ! -e ' + app + '/delete.txt && printf ABSENT') == 'ABSENT'
                    patch = '*** Begin Patch\n*** Add File: partial.txt\n+COMMITTED_FIRST\n*** Update File: ' + outside_path + '/protected.txt\n@@\n-OUTSIDE_UNCHANGED\n+MUST_NOT_CHANGE\n*** Add File: skipped.txt\n+MUST_NOT_CREATE\n*** End Patch'
                    text, rows = invoke(emulator, sid, evidence, 'permissionFailureReportsPartialCommit', 'apply_patch', {'input': patch})
                    assert 'Patch stopped after 1 of 3 operations.' in text and 'Not executed:' in text, text
                    assert agent['read_bytes'](emulator, app + '/partial.txt') == b'COMMITTED_FIRST\n'
                    assert agent['read_bytes'](emulator, outside + '/protected.txt') == b'OUTSIDE_UNCHANGED\n'
                    assert emulator.app('test ! -e ' + app + '/skipped.txt && printf ABSENT') == 'ABSENT'
                    metadata = [r['data']['meta'] for r in rows if r['type'] == 'tool/result' and r['data'].get('meta', {}).get('stopped') is True]
                    assert metadata; evidence['partialCommitPresentationMeta'] = metadata[-1]
                    emulator.rpc('commands/execute', {'agentId': sid, 'line': '/permission read-only', 'submittedAttachments': []})
                    text, _ = invoke(emulator, sid, evidence, 'readOnlyEditorRefused', 'str_replace_editor', {'command': 'str_replace', 'path': file, 'old_str': 'alpha=2', 'new_str': 'MUST_NOT_CHANGE'}, True)
                    assert 'read-only' in text
                    text, _ = invoke(emulator, sid, evidence, 'readOnlyPatchRefused', 'apply_patch', {'input': '*** Begin Patch\n*** Add File: denied.txt\n+MUST_NOT_CREATE\n*** End Patch'}, True)
                    assert 'read-only' in text
                    assert agent['read_bytes'](emulator, app + '/editor.txt') == content.encode()
                    assert emulator.app('test ! -e ' + app + '/denied.txt && printf ABSENT') == 'ABSENT'
                    text, _ = invoke(emulator, sid, evidence, 'readOnlyViewStillWorks', 'str_replace_editor', {'command': 'view', 'path': file})
                    assert '标题 🧭' in text and 'alpha=2' in text
                    unfinished = False; evidence['fileBytesAndDefaultDenialsVerified'] = True
                finally:
                    if sid and unfinished: emulator.rpc('session/cancel', {'request': {'sessionId': sid}})
            evidence['temporaryModelCredentialRemoved'] = True
    finally:
        try:
            emulator.app('rm -rf ' + app + ' ' + outside)
            assert emulator.app('test ! -e ' + app + ' && test ! -e ' + outside + ' && printf ABSENT') == 'ABSENT'
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
