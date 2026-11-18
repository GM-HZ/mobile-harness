"""Verify the real ArkWeb sign-in entry and the DSH account callback on an isolated emulator."""

import argparse
import base64
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import runpy
import threading
import time
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit
import urllib.request
import uuid

ui = runpy.run_path(str(Path(__file__).with_name('emulator-chat-import-ui.py')))
market = runpy.run_path(str(Path(__file__).with_name('emulator-plugin-market.py')))
support = ui['support']
PORT = 19770
CLIENT = {'version': '0.2.2-rc.5', 'locale': 'zh-CN', 'timezoneOffsetSeconds': 28800}
CALLBACK_ORIGIN = 'http://127.0.0.1:19592'
ACTIVE = ('initializing', 'waiting-browser', 'exchanging', 'committing')


def state(device):
    return device.rpc('account/getState', {})


def wait(check, label):
    until = time.monotonic() + 18
    while time.monotonic() < until:
        value = check()
        if value:
            return value
        time.sleep(.2)
    raise AssertionError('Did not observe ' + label)


def attempt_in(device, phase):
    attempt = state(device)['attempt']
    if attempt and attempt['phase'] == phase:
        return attempt
    if attempt and attempt['phase'] in ('failed', 'expired'):
        raise AssertionError({key: attempt.get(key) for key in ('phase', 'errorCode')})
    return None


def cancel(device):
    attempt = state(device)['attempt']
    if attempt and attempt['phase'] in ACTIVE:
        return device.rpc('account/cancelSignIn', {'attemptId': attempt['id']})
    return state(device)


def public_popup(device, evidence):
    assert state(device)['status'] == 'signed-out'
    button = ui['wait_control'](device, {'登录', 'Sign in'}, 'button')
    ui['tap'](device, button)
    try:
        back = ui['wait_control'](device, {'返回聊天'}, 'Button')
        attempt = wait(lambda: attempt_in(device, 'waiting-browser'), 'Platform authorizing state')
        destination = urlsplit(attempt['authorizeUrl'])
        assert (destination.scheme, destination.hostname, destination.path) == (
            'https', 'platform.deepseek.com', '/dsh/authorize'
        )
        ui['wait_control'](device, {'https://platform.deepseek.com'}, 'Text')
        ui['wait_control'](device, {'登录', 'Log in', 'Sign in'}, 'button')
        evidence.update(popupOpened=True, platformPageVisible=True, publicPath=destination.path)
        ui['tap'](device, back)
        wait(lambda: not ui['find'](ui['controls'](device), {'返回聊天'}), 'return from the native popup')
        evidence['returnedToDsh'] = True
    finally:
        final = cancel(device)
        assert final['status'] == 'signed-out'
        if final['attempt']:
            evidence['finalPhase'] = final['attempt']['phase']


class Platform(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def respond(self, value):
        body = json.dumps({'code': 0, 'data': {'biz_code': 0, 'biz_data': value}}).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        raw = self.rfile.read(int(self.headers.get('Content-Length', '0')))
        body = json.loads(raw) if raw else {}
        if self.path == '/auth-api/v0/dsh/auth_init':
            assert body['redirect_uri'] == CALLBACK_ORIGIN + '/oauth/callback'
            assert body['code_challenge_method'] == 'S256' and body['login_source'] == 'web'
            self.server.initial = body
            self.respond({'authorize_url': self.server.origin + '/dsh/authorize?authorize_id=acceptance',
                          'authorize_id': 'acceptance', 'expires_in': 60})
        elif self.path == '/auth-api/v0/dsh/auth_exchange':
            assert body['code'] == self.server.code
            assert body['redirect_uri'] == self.server.initial['redirect_uri']
            calculated = hashlib.sha256(body['code_verifier'].encode()).digest()
            assert base64.urlsafe_b64encode(calculated).decode().rstrip('=') == self.server.initial['code_challenge']
            self.server.pkce_checked = True
            self.respond({'user': None, 'token': self.server.token,
                          'authorized_url': self.server.origin + '/dsh/authorized?result=acceptance'})
        elif self.path == '/auth-api/v0/users/logout':
            assert self.headers.get('x-dsh-auth-token') == self.server.token
            self.respond(None)
            self.server.logout.set()
        elif self.path == '/auth-api/v0/dsh/auth_cancel':
            self.respond(None)
        else:
            self.send_error(404)


class StopRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_):
        return None


def owned_callback(device, evidence):
    profile_patch = market['PROFILE'] + '/cordis.patch.yml'
    original = market['agent']['read_bytes'](device, profile_patch)
    name = 'mh-account-' + uuid.uuid4().hex[:10]
    folder = 'alpine/workspace-native/' + name
    credential_path = support['WORKSPACE'] + '/' + name + '/credentials.yaml'
    server = ThreadingHTTPServer(('127.0.0.1', 0), Platform)
    server.origin = f'http://127.0.0.1:{PORT}'
    server.code = uuid.uuid4().hex
    server.token = 'fixture-account-' + uuid.uuid4().hex
    server.pkce_checked = False
    server.logout = threading.Event()
    threading.Thread(target=server.serve_forever, daemon=True).start()
    reverse = (f'tcp:{PORT}', f'tcp:{server.server_port}')
    connected = False
    patched = False
    try:
        assert 'Forwardport result:OK' in device.hdc('rport', *reverse)
        connected = True
        device.app('mkdir ' + folder)
        config = {'platformOrigin': server.origin, 'allowLoopbackHttp': True}
        patch = (f'\n- id: credentials\n  config: {json.dumps({"path": credential_path, "watch": False})}\n'
                 f'- id: deepseek-account\n  config: {json.dumps(config)}\n')
        device.stop()
        patched = True
        market['lsp']['restore_bytes'](device, profile_patch, original.rstrip() + patch.encode(), '/data/local/tmp/' + name)
        device.start()
        device.ready('normal')
        assert state(device)['status'] == 'signed-out'
        device.rpc('account/startSignIn', {'client': CLIENT, 'callbackOrigin': CALLBACK_ORIGIN, 'loginSource': 'web'})
        attempt = wait(lambda: attempt_in(device, 'waiting-browser'), 'test Platform authorizing state')
        assert attempt['authorizeUrl'].startswith(server.origin + '/dsh/authorize?')
        query = urlencode({'state': server.initial['state'], 'code': server.code})
        callback = urllib.request.Request(device.url + '/oauth/callback?' + query, headers={'Host': '127.0.0.1:19592'})
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), StopRedirect)
        try:
            opener.open(callback, timeout=12).close()
        except HTTPError as error:
            assert error.code == 302, error.code
            destination = urlsplit(error.headers['Location'])
            assert destination.path == '/dsh/authorized' and destination.port == PORT, destination.path
        else:
            raise AssertionError('The callback did not redirect to the fixture completion page')
        wait(lambda: attempt_in(device, 'succeeded'), 'stored synthetic account')
        status = state(device)
        assert status['status'] == 'credential-stored' and server.pkce_checked
        assert server.token not in json.dumps(status)
        evidence['pkceExchangeAndCommit'] = True
        device.stop()
        device.start()
        device.ready('normal')
        assert state(device)['status'] == 'credential-stored'
        evidence['persistedAcrossRestart'] = True
        out = device.rpc('account/signOut', {'client': CLIENT})
        assert out['status'] == 'signed-out' and server.logout.wait(8)
        evidence['signedOutAndRevoked'] = True
    finally:
        try:
            if patched:
                device.stop()
                market['lsp']['restore_bytes'](device, profile_patch, original, '/data/local/tmp/' + name + '-restore')
                device.app('rm -rf ' + folder)
                device.start()
                device.ready('normal')
                assert market['agent']['read_bytes'](device, profile_patch) == original
                assert state(device)['status'] == 'signed-out'
                evidence['originalProfileRestored'] = True
        finally:
            if connected:
                device.hdc('fport', 'rm', *reverse)
            server.shutdown()
            server.server_close()


def run(device, output):
    evidence = {'public': {}, 'fixture': {}}
    bridge = ('tcp:19643', 'tcp:19592')
    assert 'Forwardport result:OK' in device.hdc('fport', *bridge)
    try:
        device.start()
        device.ready('normal')
        public_popup(device, evidence['public'])
        owned_callback(device, evidence['fixture'])
    finally:
        device.hdc('fport', 'rm', *bridge)
        output.write_text(json.dumps(evidence, indent=2) + '\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('target')
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    run(support['Emulator'](args.target, 19643), args.output)
