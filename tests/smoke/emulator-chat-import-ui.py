"""Open the official import dialog in the actual HarmonyOS ArkWeb client."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import runpy
import time
import uuid

flow = runpy.run_path(str(Path(__file__).with_name('emulator-chat-import.py')))
support = flow['support']
APP_ID = 'org.sayact.nodepoc'
IMPORT_LABELS = {'导入 DeepSeek 会话', 'Import DeepSeek chats'}
TITLE_LABELS = {'导入 DeepSeek 会话记录', 'Import DeepSeek chat history'}


def controls(emulator):
    remote = '/data/local/tmp/mh-import-layout-' + uuid.uuid4().hex + '.json'
    try:
        emulator.hdc('shell', 'uitest', 'dumpLayout', '-b', APP_ID, '-p', remote)
        document = json.loads(emulator.hdc('shell', 'cat', remote))
    finally:
        emulator.hdc('shell', 'rm', '-f', remote)
    stack = [document]
    rows = []
    while stack:
        node = stack.pop()
        stack.extend(node.get('children', []))
        item = node.get('attributes', {})
        rows.append({key: item.get(key, '') for key in ['type', 'text', 'description', 'bounds']})
    return rows


def find(rows, labels, kind=None):
    return next((row for row in rows if (kind is None or row['type'] == kind)
                 and (row['text'] in labels or row['description'] in labels)), None)


def wait_control(emulator, labels, kind=None):
    until = time.monotonic() + 12
    while time.monotonic() < until:
        row = find(controls(emulator), labels, kind)
        if row:
            return row
        time.sleep(.2)
    raise AssertionError(f'No {kind or "control"} with label {labels} in the actual UI')


def tap(emulator, row):
    left, top, right, bottom = map(int, re.findall(r'\d+', row['bounds']))
    assert right > left and bottom > top, row
    emulator.hdc('shell', 'uitest', 'uiInput', 'click', str((left+right)//2), str((top+bottom)//2))


def open_sidebar(emulator):
    rows = controls(emulator)
    if find(rows, {'开始使用', 'Get started'}, 'dialog'):
        tap(emulator, wait_control(emulator, {'关闭', 'Close'}, 'button'))
    rows = controls(emulator)
    opener = find(rows, {'打开侧边栏', 'Open sidebar'}, 'button')
    if opener is not None:
        tap(emulator, opener)
    wait_control(emulator, {'新建会话', 'New session', '新建聊天', 'New chat'}, 'button')


def run(emulator, output):
    evidence = {}
    originals = {}
    nonce = '/data/local/tmp/mh-import-ui-' + uuid.uuid4().hex
    try:
        emulator.ready('normal')
        originals = {path: flow['agent']['read_bytes'](emulator, path) for path in [
            flow['PROFILE']+'/package.json', flow['PROFILE']+'/pnpm-lock.yaml', 'mobile-harness-boot.json',
        ]}
        flow['bundle'](emulator, False)
        evidence['enabledReadyMs'] = flow['switch'](emulator, True)
        open_sidebar(emulator)
        evidence['importButton'] = wait_control(emulator, IMPORT_LABELS, 'button')
        tap(emulator, evidence['importButton'])
        evidence['importDialog'] = wait_control(emulator, TITLE_LABELS, 'dialog')
        evidence['exportFileControl'] = wait_control(emulator, {'导出文件', 'Export file'})
        evidence['disabledReadyMs'] = flow['switch'](emulator, False)
        open_sidebar(emulator)
        assert find(controls(emulator), IMPORT_LABELS, 'button') is None
        evidence['buttonRemovedAfterDisable'] = True
    finally:
        try:
            if originals:
                emulator.stop()
                for i, (path, body) in enumerate(originals.items()):
                    flow['lsp']['restore_bytes'](emulator, path, body, nonce+str(i))
                emulator.start()
                evidence['restoredReadyMs'] = emulator.ready('normal')
                after = {path: flow['agent']['read_bytes'](emulator, path) for path in originals}
                assert after == originals
                evidence['restoredConfigurationHashes'] = {
                    path: hashlib.sha256(body).hexdigest() for path, body in after.items()
                }
        finally:
            output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2)+'\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('target')
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    emulator = support['Emulator'](args.target, 19643)
    forward = ('tcp:19643', 'tcp:19592')
    emulator.hdc('fport', *forward)
    try:
        run(emulator, args.output)
    finally:
        emulator.hdc('fport', 'rm', *forward)
