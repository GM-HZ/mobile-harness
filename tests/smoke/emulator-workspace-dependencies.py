"""Query the actual DSH tool and execute the returned mobile paths in approved Bash."""

import argparse
import json
import os
from pathlib import Path
import runpy
import shlex
import tempfile
import time
import uuid

agent = runpy.run_path(str(Path(__file__).with_name('emulator-agent-continuation.py')))
toolkit = agent['toolkit']
support = agent['support']
restore_bytes = runpy.run_path(str(Path(__file__).with_name('emulator-lsp-lifecycle.py')))['restore_bytes']
NAME = 'load_workspace_dependencies'
LOCK = Path(__file__).resolve().parents[2] / 'runtime/harmonyos/dsh/office-wheels.json'
PROBE = """import json
from importlib.metadata import distribution, version
from pathlib import Path
import sys

from docx import Document
from lxml import etree
import numpy as np
from openpyxl import load_workbook
import pandas as pd
from PIL import Image
from pptx import Presentation
import xlsxwriter

expected = json.loads(sys.argv[1])
root = Path(sys.argv[2])
actual = {name: version(name) for name in expected}
assert actual == expected, actual
for name in expected.keys() - {"pip"}:
    assert Path(distribution(name).locate_file("")).resolve() == root, name

matrix = np.array([[2, 3], [5, 7]])
assert int((matrix @ matrix)[1, 0]) == 45
with xlsxwriter.Workbook("test.xlsx") as book:
    sheet = book.add_worksheet()
    sheet.write(0, 0, "amount")
    sheet.write(1, 0, 42)
assert load_workbook("test.xlsx").active["A2"].value == 42
assert int(pd.read_excel("test.xlsx")["amount"].sum()) == 42
document = Document()
document.add_paragraph("mobile-office")
document.save("test.docx")
assert Document("test.docx").paragraphs[0].text == "mobile-office"
deck = Presentation()
deck.slides.add_slide(deck.slide_layouts[0]).shapes.title.text = "mobile-office"
deck.save("test.pptx")
assert Presentation("test.pptx").slides[0].shapes.title.text == "mobile-office"
Image.new("RGB", (4, 3), "green").save("test.png")
assert Image.open("test.png").size == (4, 3)
assert etree.fromstring(b"<probe><item>42</item></probe>").find("item").text == "42"
print("HARMONY_OFFICE_TOOLKIT:" + json.dumps({"python": sys.version.split()[0], "distributions": actual,
      "formats": ["xlsx", "docx", "pptx", "png", "xml"], "numpyDot": True}))
"""


def advertised(rows):
    header = next(row['data']['header'] for row in rows if row['type'] == 'request/header')
    tools = {row['name'] for row in header['tools']}
    assert {'read', 'bash'} <= tools
    return NAME in tools


def run(device, output, expect_absent, port):
    name = 'mh-workspace-dependencies-' + uuid.uuid4().hex[:10]
    folder = 'alpine/workspace-native/' + name
    bridge = (f'tcp:{port}', 'tcp:19592')
    assert 'Forwardport result:OK' in device.hdc('fport', *bridge)
    evidence = {}
    remote = '/data/local/tmp/' + name
    profile = 'alpine/native-benchmark-home/profiles/web/cordis.patch.yml'
    original = None
    workspace = session = None
    try:
        started = time.monotonic()
        device.start()
        device.ready('normal')
        evidence['initialReadyMs'] = round((time.monotonic() - started) * 1000)
        original = agent['read_bytes'](device, profile)
        assert device.rpc('permissionPresets/catalog', {})['defaultPreset'] == 'workspace-write'
        device.app('mkdir ' + folder)
        path = support['WORKSPACE'] + '/' + name
        workspace = device.rpc('workspace/create', {'request': {'path': path}})['workspace']['workspaceId']
        with support['model_key'](device):
            session = device.rpc('session/create', {'request': {'workspaceId': workspace}})['sessionId']
            evidence['sessionId'] = session
            device.rpc('session/selectModel', {'request': {'sessionId': session, 'provider': 'deepseek-official',
                       'model': 'deepseek-flash', 'reasoningEffort': 'off'}})
            query = 'Call load_workspace_dependencies once with {}. If it is not exposed, reply TOOL_ABSENT. Use no other tools.'
            calls, results, rows = agent['prompt'](device, session, query)
            evidence['advertised'] = advertised(rows)
            if expect_absent:
                assert not calls and not evidence['advertised']
                return
            assert [row['name'] for row in calls] == [NAME] and evidence['advertised']
            discovered = json.loads(toolkit['texts'](results))
            evidence['resolved'] = discovered
            expected = {row['name']: row['version'] for row in json.loads(LOCK.read_text())['wheels']}
            assert discovered['pythonDistributions'] == dict(expected, pip='25.0.1')
            assert discovered['python'] == '/usr/bin/python3' and discovered['node'] == '/bin/node'
            assert discovered['pnpm'] == '/pnpm-harmony-v2/bin/pnpm.mjs'
            evidence['readOnlyLookup'] = True
            skill, _ = agent['tool'](device, session, 'skill', {'name': 'office-xlsx'})
            assert 'Otherwise call `load_workspace_dependencies`' in toolkit['texts']([skill])
            evidence['officeSkillUsesBundledRuntime'] = True
            python_args = [
                discovered['python'], 'workspace-check.py',
                json.dumps(discovered['pythonDistributions']), discovered['pythonPackages'],
            ]
            commands = [python_args, [discovered['node'], '--version'],
                [discovered['node'], discovered['pnpm'], '--version'],
                [discovered['node'], discovered['pnpm'], 'exec', 'node', '-p', '"mh-pnpm-exec"'],
                ['test', '-d', discovered['nodePackages']]]
            script = 'set -eu\n' + '\n'.join(map(shlex.join, commands)) + '\n'
            with tempfile.TemporaryDirectory() as directory:
                for filename, body in [('workspace-check.py', PROBE), ('run-workspace-check.sh', script),
                                       ('package.json', '{}\n')]:
                    fixture = Path(directory) / filename
                    fixture.write_text(body)
                    assert 'FileTransfer finish' in device.hdc('file', 'send', str(fixture), remote)
                    device.app(f'cp {remote} {folder}/{filename}')
            command = 'bash ./run-workspace-check.sh'
            args = {'command': command, 'description': 'Run the bundled workspace dependency fixture',
                    'timeoutMs': 90000, 'sandbox_permissions': 'danger-full-access',
                    'justification': 'Execute only the owned, offline document and interpreter regression.'}
            with toolkit['approval']['approval_events'](device) as events:
                calls, results = toolkit['prompt'](device, session,
                    'Actually call bash once with exactly this JSON. Use no other tools: ' + json.dumps(args),
                    events, command, timeout=120)
            assert len(calls) == len(results) == 1 and not results[0]['isError'], toolkit['texts'](results)
            lines = toolkit['texts'](results).splitlines()
            marker = 'HARMONY_OFFICE_TOOLKIT:'
            line, = [line for line in lines if line.startswith(marker)]
            evidence['offlinePython'] = json.loads(line[len(marker):])
            assert 'v24.14.1' in lines and '11.28.5' in lines, lines
            assert 'mh-pnpm-exec' in lines, lines
            evidence['node'] = '24.14.1'
            evidence['pnpm'] = '11.28.5'
            evidence['pnpmExec'] = True
            evidence['exactBashApproval'] = True
            device.stop()
            device.start()
            evidence['restartReadyMs'] = device.ready('normal')
            calls, results, _ = agent['prompt'](device, session, query)
            assert [row['name'] for row in calls] == [NAME]
            assert json.loads(toolkit['texts'](results)) == discovered
            evidence['samePathsAfterRestart'] = True
        evidence['temporaryCredentialRemoved'] = True
    finally:
        try:
            if session:
                device.rpc('workspace/archiveSession', {'request': {'sessionId': session}})
            if workspace:
                assert device.rpc('workspace/delete', {'request': {'workspaceId': workspace}}) == {'deleted': True}
            device.app('rm -rf ' + folder)
            device.hdc('shell', 'rm', '-f', remote)
            if original is not None:
                if agent['read_bytes'](device, profile) != original:
                    device.stop()
                    restore_bytes(device, profile, original, remote + '-profile')
                    device.start()
                    device.ready('normal')
                assert agent['read_bytes'](device, profile) == original
                evidence['originalProfileRestored'] = True
        finally:
            device.hdc('fport', 'rm', *bridge)
            output.write_text(json.dumps(evidence, indent=2) + '\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('target')
    parser.add_argument('output', type=Path)
    parser.add_argument('--port', type=int, default=19643)
    parser.add_argument('--expect-absent', action='store_true')
    args = parser.parse_args()
    if not os.environ.get('MH_TEST_DEEPSEEK_API_KEY'):
        parser.error('MH_TEST_DEEPSEEK_API_KEY is required')
    run(support['Emulator'](args.target, args.port), args.output, args.expect_absent, args.port)
