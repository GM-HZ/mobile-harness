"""Drive the packaged GitHub CLI's device flow from the native Forge-account page."""
import argparse
import json
from http.server import ThreadingHTTPServer
from pathlib import Path
import runpy
import tempfile
import threading
import time
from urllib.parse import urlsplit
import uuid

forge = runpy.run_path(str(Path(__file__).with_name('emulator-forge-github.py')))
ui = runpy.run_path(str(Path(__file__).with_name('emulator-chat-import-ui.py')))
agent, support, lsp = (forge[name] for name in ('agent', 'support', 'lsp'))
HOSTS = ('github.com', 'api.github.com')
ACCOUNT = 'fixture-owner'
CODE = 'MHST-TEST'
TOKEN = 'gho_owned_fixture_not_a_real_credential'
STATUS = 'alpine/tmp/github-account/status.json'
FORGE = forge['flow']['FORGE']


class DeviceAuthFixture(forge['GitHubFixture']):
    def do_POST(self):
        path = urlsplit(self.path).path
        if self.headers.get('Content-Length'):
            self.rfile.read(int(self.headers['Content-Length']))
        if path == '/login/device/code':
            self.server.calls.append('issue')
            self.reply(200, {'device_code': 'owned-device-code', 'user_code': CODE,
                             'verification_uri': 'https://github.com/login/device',
                             'expires_in': 900, 'interval': 1})
        elif path == '/login/oauth/access_token':
            if self.server.approved.is_set():
                self.server.calls.append('exchange')
                self.reply(200, {'access_token': TOKEN, 'scope': 'repo,read:org,gist', 'token_type': 'bearer'})
            else:
                self.reply(200, {'error': 'authorization_pending'})
        elif path == '/graphql' and self.authenticated():
            self.server.calls.append('viewer')
            self.reply(200, {'data': {'viewer': {'login': ACCOUNT}}})
        else:
            self.reply(403, {'message': 'Unexpected OAuth fixture request'})

    def authenticated(self):
        return self.headers.get('Authorization') in ('token '+TOKEN, 'Bearer '+TOKEN)

    def do_GET(self):
        path = urlsplit(self.path).path
        if not self.authenticated():
            self.reply(401, {'message': 'Bad credentials'})
        elif path == '/repos/fixture/mobile/contents/proof.txt':
            self.server.calls.append('forge-read')
            self.reply(200, 'Forge used the device account.\n', 'text/plain')
        else:
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('X-OAuth-Scopes', 'repo, read:org, gist')
            self.end_headers()
            self.wfile.write(b'{}')

    def do_HEAD(self):
        self.send_response(200 if self.authenticated() else 401)
        self.send_header('X-OAuth-Scopes', 'repo, read:org, gist')
        self.end_headers()


def tap(device, *texts):
    for attempt in range(3):
        try:
            control = ui['wait_control'](device, set(texts))
            break
        except json.JSONDecodeError:
            if attempt == 2:
                raise
            time.sleep(.2)
    ui['tap'](device, control)


def open_account(device):
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        rows = ui['controls'](device)
        if ui['find'](rows, {'开始使用', 'Get started'}, 'dialog'):
            tap(device, '关闭', 'Close')
        elif ui['find'](rows, {'预览版说明', 'Preview Notice'}, 'dialog'):
            tap(device, '继续', 'Continue')
        elif menu := ui['find'](rows, {'账号菜单', 'Account menu'}):
            ui['tap'](device, menu)
            break
        elif sidebar := ui['find'](rows, {'打开侧边栏', 'Open sidebar'}, 'button'):
            ui['tap'](device, sidebar)
        else:
            time.sleep(.2)
    else:
        raise AssertionError('DSH account menu was not available')
    tap(device, '设置', 'Settings')
    general = ui['find'](ui['controls'](device), {'通用设置', 'General settings', 'General'})
    if general:
        ui['tap'](device, general)
    for _ in range(10):
        button = ui['find'](ui['controls'](device), {'管理账号', 'Manage account'})
        if button:
            ui['tap'](device, button)
            ui['wait_control'](device, {'Forge GitHub 账号'})
            return
        device.hdc('shell','uitest','uiInput','swipe','1080','1790','1080','670')
        time.sleep(.2)
    raise AssertionError('The Forge account action was not found in General settings')


def state(device, phase):
    end = time.monotonic()+22
    while time.monotonic()<end:
        if device.app('test -f '+STATUS+' && printf READY')=='READY':
            snapshot = json.loads(device.app('cat '+STATUS))
            assert set(snapshot) <= {'id', 'phase', 'code', 'account'}
            if snapshot['phase']==phase:
                return snapshot
            if snapshot['phase']=='failed':
                raise AssertionError('GitHub CLI reported an unsuccessful action')
        time.sleep(.25)
    raise AssertionError('GitHub CLI did not reach '+phase)


def run(device, output, port):
    forward = (f'tcp:{port}', 'tcp:19592')
    assert 'Forwardport result:OK' in device.hdc('fport', *forward)
    workspace = sid = reverse = oauth = proxy = None
    own_config = False
    originals = {}
    report = {}
    name = 'mh-forge-device-' + uuid.uuid4().hex[:10]
    folder = 'alpine/workspace-native/'+name
    profile = forge['flow']['PROFILE']
    paths = [profile+'/'+s for s in ('package.json', 'pnpm-lock.yaml', 'cordis.patch.yml')]
    paths.append(forge['CA_BUNDLE'])
    try:
        device.ready('normal')
        assert device.app('test ! -e '+forge['GH_CONFIG']+'/hosts.yml && printf ABSENT')=='ABSENT'
        own_config = True
        originals = {p: forge['saved_file'](device, p) for p in paths}
        with tempfile.TemporaryDirectory(prefix=name) as temp:
            context, cert = forge['make_tls'](Path(temp), HOSTS)
            oauth = ThreadingHTTPServer(('127.0.0.1', 0), DeviceAuthFixture)
            oauth.socket = context.wrap_socket(oauth.socket, server_side=True)
            oauth.approved = threading.Event()
            oauth.calls = []
            threading.Thread(target=oauth.serve_forever, daemon=True).start()
            proxy = ThreadingHTTPServer(('127.0.0.1', 0), forge['ConnectProxy'])
            proxy.hosts, proxy.destination = HOSTS, oauth.server_port
            threading.Thread(target=proxy.serve_forever, daemon=True).start()
            bridge = ('tcp:19773', f'tcp:{proxy.server_port}')
            assert 'Forwardport result:OK' in device.hdc('rport', *bridge)
            reverse = bridge
            enabled = device.rpc('pluginManager/setBundleEnabled', {'name': FORGE, 'enabled': True})
            assert enabled['application'] in ('applied', 'restart-required')
            current = agent['read_bytes'](device, paths[2]).rstrip()
            if current == b'[]' or current.endswith(b'\n[]'):
                current = current[:-2].rstrip()
            device.stop()
            device.app('mkdir '+folder)
            remote = '/data/local/tmp/'+name
            module = 'file://'+support['WORKSPACE']+'/'+name+'/proxy.mjs'
            overlay = ('\n- insert:\n    - id: '+name+'\n      name: '+json.dumps(module)+'\n').encode()
            lsp['restore_bytes'](device, paths[2], current+overlay, remote+'-profile')
            lsp['restore_bytes'](device, forge['CA_BUNDLE'], originals[forge['CA_BUNDLE']]+b'\n'+cert, remote+'-ca')
            lsp['restore_bytes'](device, folder+'/proxy.mjs',
                                 b'export function apply() { process.env.HTTPS_PROXY = "http://127.0.0.1:19773"; }\n',
                                 remote+'-proxy')
            device.start()
            device.ready('normal')
            open_account(device)
            ui['wait_control'](device, {'此设备未登录 GitHub。'})
            tap(device, '登录 GitHub')
            ui['wait_control'](device, {CODE})
            assert state(device, 'authorize')['code']==CODE
            tap(device, '取消登录')
            state(device, 'canceled')
            assert device.app('test ! -e '+forge['GH_CONFIG']+'/hosts.yml && printf ABSENT')=='ABSENT'
            report['nativeLoginCanCancelBeforeConsent'] = True
            tap(device, '登录 GitHub')
            ui['wait_control'](device, {CODE})
            ui['wait_control'](device, {'打开 GitHub 授权页'})
            oauth.approved.set()
            assert state(device, 'signed-in')['account']==ACCOUNT
            ui['wait_control'](device, {'已登录 '+ACCOUNT})
            report['nativeLoginAndCliStorage'] = True
            tap(device, '返回会话')
            device.stop()
            device.start()
            device.ready('normal')
            open_account(device)
            ui['wait_control'](device, {'已登录 '+ACCOUNT})
            report['accountRestoredAfterRestart'] = True
            workspace = device.rpc('workspace/create', {'request': {'path': support['WORKSPACE']+'/'+name}})['workspace']['workspaceId']
            sid = device.rpc('session/create', {'request': {'workspaceId': workspace}})['sessionId']
            args = {'sessionId': sid, 'url': 'https://github.com/fixture/mobile/pull/7'}
            device.rpc('forgePanel/track', args)
            result = device.rpc('forgePanel/changeRequestText', {**args, 'commit': 'a'*40, 'path': 'proof.txt'})
            assert result=='Forge used the device account.' and 'forge-read' in oauth.calls
            report['forgeUsesDeviceCredential'] = True
            tap(device, '退出 GitHub 登录')
            state(device, 'signed-out')
            ui['wait_control'](device, {'此设备未登录 GitHub。'})
            tap(device, '返回会话')
            report['nativeLogout'] = True
    finally:
        try:
            if sid:
                device.rpc('workspace/archiveSession', {'request': {'sessionId': sid}})
            if workspace:
                device.rpc('workspace/delete', {'request': {'workspaceId': workspace}})
            if originals:
                device.stop()
                device.app('rm -rf '+folder)
                if own_config:
                    device.app('rm -rf '+forge['GH_CONFIG'])
                for i, (p, content) in enumerate(originals.items()):
                    if content is None:
                        device.app('rm -f '+p)
                    else:
                        lsp['restore_bytes'](device, p, content, '/data/local/tmp/'+name+str(i))
                device.start()
                device.ready('normal')
                assert all(forge['saved_file'](device, p)==value for p, value in originals.items())
                report['profileAndTLSRestored'] = True
        finally:
            if reverse:
                device.hdc('fport','rm',*reverse)
            device.hdc('fport','rm',*forward)
            for server in (proxy, oauth):
                if server:
                    server.shutdown()
                    server.server_close()
            if oauth:
                report['fixtureOperations'] = oauth.calls
            output.write_text(json.dumps(report, indent=2)+'\n')


if __name__=='__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('target')
    parser.add_argument('output', type=Path)
    parser.add_argument('--port', type=int, default=19652)
    args = parser.parse_args()
    run(support['Emulator'](args.target, args.port), args.output, args.port)
