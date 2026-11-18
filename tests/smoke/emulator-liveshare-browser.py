"""Submit visitor attachments from the actual DSH share page in Chrome."""
import argparse
import base64
import json
import os
from pathlib import Path
import re
import runpy
import subprocess
from tempfile import TemporaryDirectory
import uuid

SMOKE = Path(__file__).resolve().parent
relay = runpy.run_path(str(SMOKE/'emulator-liveshare-relay.py'))
vision = runpy.run_path(str(SMOKE/'emulator-deepseek-vision.py'))
DRIVER = SMOKE/'fixtures/liveshare-viewer-browser.js'
PACKAGE = ('alpine/.dsh-0.2.2-rc.5/dsh/node_modules/@deepseek-ai/'
           'dsh-experimental-liveshare-protocol/lib/index.js')
CARRIER_SCRIPT = """
import fs from 'node:fs';
const [source, shareId, sessionId] = JSON.parse(fs.readFileSync(0, 'utf8'));
const { viewerCarrierScript } = await import('data:text/javascript;base64,' + source);
console.log(viewerCarrierScript({ basePath: '', shareId, sessionId, readTimeoutMs: 28000 }));
"""


def browser_result(cli, payload):
    command = [str(cli)]
    if cli.suffix == '.sh':
        command.insert(0, 'bash')
    command.append('-s=mh-share-' + uuid.uuid4().hex[:12])
    with TemporaryDirectory(prefix='mh-share-browser-') as directory:
        script = Path(directory)/'driver.js'
        script.write_text('async (page) => (' + DRIVER.read_text() + ')(page,' + json.dumps(payload) + ')')
        try:
            subprocess.run(command+['open', '--browser', 'chrome', '--idle-timeout', '120000'],
                           cwd=directory, text=True, capture_output=True, check=True, timeout=30)
            result = subprocess.run(command+['run-code', '--filename', str(script)],
                                    cwd=directory, text=True, capture_output=True, check=True, timeout=90)
            for line in result.stdout.splitlines():
                if line.startswith('"MH_'):
                    value = json.loads(line)
                    kind, _, data = value.partition(':')
                    assert kind == 'MH_RESULT', data
                    return json.loads(data)
            raise AssertionError('Playwright returned no viewer test result')
        finally:
            subprocess.run(command+['close'], cwd=directory, text=True, capture_output=True, timeout=15)


def verify(device, port, share, session, _outside, html, evidence, cli):
    files = [
        ('first.png', 'image/png', vision['sample']('yellow', 'green')),
        ('second.png', 'image/png', vision['sample']('blue', 'red')),
        ('visitor.txt', 'text/plain', b'Owned fixture uploaded using the actual viewer composer.'),
    ]
    source = relay['agent']['read_bytes'](device, PACKAGE)
    node = Path(os.environ.get('DEVECO_HOME', '/Applications/DevEco-Studio.app/Contents'))/'tools/node/bin/node'
    carrier = subprocess.run([str(node), '--input-type=module', '-e', CARRIER_SCRIPT],
                             input=json.dumps([base64.b64encode(source).decode(), share, str(session)]),
                             text=True, capture_output=True, check=True).stdout
    document, count = re.subn(r'<head(?:\s[^>]*)?>', lambda m: m[0] + '<script>' + carrier + '</script>',
                              html.decode(), count=1, flags=re.I)
    assert count == 1
    browser = browser_result(cli, {
        'base': f'http://127.0.0.1:{port}', 'share': share, 'session': str(session), 'html': document,
        'files': [{'name': name, 'type': media, 'data': base64.b64encode(data).decode()}
                  for name, media, data in files],
        'prompt': ('Read the two images in order. Each has two vertical solid halves. Return only the four English '
                   'color names, left then right, separated by spaces. Ignore the text attachment and do not use tools.'),
    })
    message, reply, end = relay['observed_viewer_turn'](device, share, session, browser['requestId'])
    assert reply.lower().split() == ['yellow', 'green', 'blue', 'red'], reply
    assert len([block for block in message['content'] if block['type'] == 'image']) == 2
    evidence['actualChromeViewer'] = {**browser, 'modelReply': reply, 'turnEndReason': end,
                                     'visitorPrincipal': message['source']['principal']}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('target')
    parser.add_argument('output', type=Path)
    parser.add_argument('--playwright-cli', type=Path, required=True)
    parser.add_argument('--host-port', type=int, default=19652)
    args = parser.parse_args()
    if not os.environ.get('MH_TEST_DEEPSEEK_API_KEY'):
        parser.error('MH_TEST_DEEPSEEK_API_KEY is required for the actual model turn')
    cli = args.playwright_cli.resolve(strict=True)

    def guest_check(device, port, share, session, outside, html, evidence):
        verify(device, port, share, session, outside, html, evidence, cli)

    relay['run'](relay['support']['Emulator'](args.target, args.host_port), args.output,
                 False, False, args.host_port, False, guest_check=guest_check)
