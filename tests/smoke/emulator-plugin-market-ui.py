"""Verify the official Discover page and install confirmation in ArkWeb."""
import argparse
import hashlib
from http.server import ThreadingHTTPServer
import json
import os
from pathlib import Path
import runpy
import threading
import uuid

market = runpy.run_path(str(Path(__file__).with_name('emulator-plugin-market.py')))
ui = runpy.run_path(str(Path(__file__).with_name('emulator-chat-import-ui.py')))
support, agent, lsp = (market[key] for key in ['support', 'agent', 'lsp'])
TITLE = 'Harmony market fixture'


def run(emulator, output):
    fixture = 'mh-market-ui-' + uuid.uuid4().hex[:10]
    remote = '/data/local/tmp/' + fixture
    profile = market['PROFILE']
    originals = {}
    evidence = {}
    server = ThreadingHTTPServer(('127.0.0.1', 0), market['Registry'])
    device_port = market['DEVICE_PORT']
    server.base = f'http://127.0.0.1:{device_port}'
    server.requests, server.responses = [], {}
    root = support['WORKSPACE'].rsplit('/', 1)[0]
    market['populate'](server, fixture, root, support['WORKSPACE'] + '/' + fixture)
    reverse = (f'tcp:{device_port}', f'tcp:{server.server_port}')
    threading.Thread(target=server.serve_forever, daemon=True).start()
    connected = False
    try:
        emulator.ready('normal')
        for file in [profile+'/package.json', profile+'/pnpm-lock.yaml', profile+'/cordis.patch.yml', 'mobile-harness-boot.json']:
            originals[file] = agent['read_bytes'](emulator, file) if emulator.app(f'test -f {file} && printf PRESENT') == 'PRESENT' else None
        market['market'](emulator, False)
        reply = emulator.hdc('rport', *reverse)
        assert 'Forwardport result:OK' in reply, reply
        connected = True
        with support['model_key'](emulator):
            evidence['enabledReadyMs'] = market['switch'](emulator, True)
            emulator.rpc('pluginMarket/setIndexes', {'urls': [server.base+'/market.json']})
            ui['open_sidebar'](emulator)
            ui['tap'](emulator, ui['wait_control'](emulator, {'插件', 'Plugins'}, 'button'))
            evidence['discoverTab'] = ui['wait_control'](emulator, {'发现', 'Discover'})
            ui['tap'](emulator, evidence['discoverTab'])
            evidence['listedEntry'] = ui['wait_control'](emulator, {'查看 '+TITLE, 'View '+TITLE}, 'button')
            install = ui['wait_control'](emulator, {'安装 '+TITLE, 'Install '+TITLE}, 'button')
            ui['tap'](emulator, install)
            evidence['installConfirmation'] = ui['wait_control'](emulator, {'安装「'+TITLE+'」？', 'Install "'+TITLE+'"?'},
                                                                 'dialog')
            evidence['displayedRegistry'] = ui['wait_control'](emulator, {server.base+'/'})
            ui['tap'](emulator, ui['wait_control'](emulator, {'取消', 'Cancel'}, 'button'))
            assert market['catalog'](emulator, fixture) is None
            assert not any(path.endswith('.tgz') for path in server.requests), server.requests
            evidence['cancelledBeforeDownloadOrInstall'] = True
            emulator.rpc('pluginMarket/setIndexes', {'urls': []})
            evidence['disabledReadyMs'] = market['switch'](emulator, False)
        evidence['testCredentialRemoved'] = True
    finally:
        try:
            if originals:
                emulator.stop()
                for i, (file, body) in enumerate(originals.items()):
                    if body is None:
                        emulator.app('rm -f ' + file)
                    else:
                        lsp['restore_bytes'](emulator, file, body, remote+'-'+str(i))
                emulator.start()
                evidence['restoredReadyMs'] = emulator.ready('normal')
                for file, body in originals.items():
                    if body is None:
                        assert emulator.app(f'test ! -e {file} && printf ABSENT') == 'ABSENT'
                    else:
                        assert agent['read_bytes'](emulator, file) == body
                evidence['restoredConfigurationHashes'] = {
                    file: hashlib.sha256(body).hexdigest() if body is not None else None for file, body in originals.items()
                }
        finally:
            if connected:
                emulator.hdc('fport', 'rm', *reverse)
                assert ' '.join(reverse) not in emulator.hdc('fport', 'ls')
            server.shutdown()
            server.server_close()
            output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2)+'\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('target')
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    if not os.environ.get('MH_TEST_DEEPSEEK_API_KEY'):
        parser.error('MH_TEST_DEEPSEEK_API_KEY is required for the configured-client fixture')
    emulator = support['Emulator'](args.target, 19643)
    forward = ('tcp:19643', 'tcp:19592')
    emulator.hdc('fport', *forward)
    try:
        run(emulator, args.output)
    finally:
        emulator.hdc('fport', 'rm', *forward)
