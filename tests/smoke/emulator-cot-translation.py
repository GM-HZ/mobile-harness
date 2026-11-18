"""Exercise the optional translation bundle in the actual Phone ArkWeb client."""
import argparse
from contextlib import contextmanager
import hashlib
from http.client import HTTPResponse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import runpy
import select
import socket
import subprocess
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener, getproxies
import uuid

flow = runpy.run_path(str(Path(__file__).with_name('emulator-chat-import.py')))
market = runpy.run_path(str(Path(__file__).with_name('emulator-plugin-market.py')))
inspector = runpy.run_path(str(Path(__file__).with_name('emulator-inspector.py')))
ui = runpy.run_path(str(Path(__file__).with_name('emulator-chat-import-ui.py')))
support, agent, lsp = (flow[key] for key in ['support', 'agent', 'lsp'])
approval = inspector['approval']
PROFILE = flow['PROFILE']
NAME = '@deepseek-ai/dsh-experimental-cot-translation-bundle'
SOURCE = 'Search only the archived export context.'
FIXTURE_TRANSLATIONS = {('bing', 'zh-Hans'): '只搜索归档导出中的上下文。',
                        ('google', 'ja'): 'アーカイブ内のコンテキストだけを検索します。'}
BODY = '[data-cot-translation="true"]'
DISCLOSURE = '[data-variant="think"] [data-disclosure-row]'
SERVER_PORT = 19747
PUBLIC_ENDPOINTS = {
    'bing': 'https://edge.microsoft.com/translate/translatetext',
    'google': 'https://translate.googleapis.com/translate_a/single',
}
HARNESS_ENV = 'alpine/native-benchmark-home/.env'


class RefuseRedirects(HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


def proxy_endpoint():
    proxy = getproxies().get('https', '')
    endpoint = urlsplit(proxy)
    if (endpoint.scheme != 'http' or endpoint.hostname not in {'localhost', '127.0.0.1', '::1'}
            or endpoint.username is not None or endpoint.password is not None or not endpoint.port
            or endpoint.path not in {'', '/'} or endpoint.query or endpoint.fragment):
        raise ValueError('Use an existing unauthenticated HTTP CONNECT proxy on Mac loopback')
    return endpoint


def public_proxy():
    return build_opener(ProxyHandler({'https': proxy_endpoint().geturl()}), RefuseRedirects())


def profile_bytes(emulator, file):
    if file in {PROFILE + '/pnpm-lock.yaml', HARNESS_ENV} and emulator.app(f'test -e {file} || printf MISSING') == 'MISSING':
        return None
    return agent['read_bytes'](emulator, file)


class ConnectProxy(BaseHTTPRequestHandler):
    authorities = {urlsplit(endpoint).hostname + ':443' for endpoint in PUBLIC_ENDPOINTS.values()}

    def log_message(self, *_):
        pass

    def do_CONNECT(self):
        if self.path not in self.authorities:
            self.send_error(403)
            return
        target = self.server.upstream
        mark = {'authority': self.path}
        self.server.calls.append(mark)
        with socket.create_connection((target.hostname, target.port), timeout=10) as upstream:
            upstream.sendall(f'CONNECT {self.path} HTTP/1.1\r\nHost: {self.path}\r\n\r\n'.encode('ascii'))
            with HTTPResponse(upstream, method='CONNECT') as response:
                response.begin()
                mark['connectStatus'] = response.status
            if mark['connectStatus'] != 200:
                self.send_error(502)
                return
            self.send_response_only(200, 'Connection established')
            self.end_headers()
            clients = {self.connection: upstream, upstream: self.connection}
            try:
                while readable := select.select(list(clients), [], [], 18)[0]:
                    for client in readable:
                        chunk = client.recv(65536)
                        if not chunk:
                            return
                        clients[client].sendall(chunk)
            except (BrokenPipeError, ConnectionResetError):
                pass


class Provider(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_POST(self):
        url = urlsplit(self.path)
        provider = url.path.strip('/')
        length = int(self.headers.get('Content-Length', '0'))
        if not 0 < length <= 512:
            self.send_error(400)
            return
        body = self.rfile.read(length)
        params = parse_qs(url.query)
        if provider == 'bing':
            text, = json.loads(body)
            target, = params['to']
            shape = params == {'to': [target], 'isEnterpriseClient': ['false']} and self.headers.get_content_type() == 'application/json'
        elif provider == 'google':
            form = parse_qs(body.decode())
            text, = form['q']
            target, = form['tl']
            shape = not params and form == {'q': [SOURCE], 'tl': [target], 'sl': ['auto'], 'client': ['gtx'], 'dt': ['t']}
            shape = shape and self.headers.get_content_type() == 'application/x-www-form-urlencoded'
        else:
            self.send_error(404)
            return
        record = {'provider': provider, 'target': target, 'text': text, 'requestShape': shape,
                  'authorization': bool(self.headers.get('Authorization')), 'cookie': bool(self.headers.get('Cookie'))}
        self.server.calls.append(record)
        if self.server.public_proxy is not None:
            if not shape or text != SOURCE or target != {'bing': 'zh-Hans', 'google': 'zh-CN'}[provider] or record['authorization'] or record['cookie']:
                self.send_error(400)
                return
            self.forward_public(provider, url.query, body, record)
            return
        if self.server.hold:
            self.server.started.set()
            if select.select([self.connection], [], [], 14)[0]:
                try:
                    if not self.connection.recv(1, socket.MSG_PEEK):
                        self.server.closed.set()
                except ConnectionResetError:
                    self.server.closed.set()
            return
        if self.server.fail:
            self.send_error(503)
            return
        translated = FIXTURE_TRANSLATIONS[(provider, target)]
        data = [{ 'translations': [{'text': translated, 'to': target}]}] if provider == 'bing' else [[[translated, text, None, None]], None, 'en']
        result = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(result)))
        self.end_headers()
        self.wfile.write(result)

    def forward_public(self, provider, query, body, record):
        url = PUBLIC_ENDPOINTS[provider] + ('?' + query if query else '')
        request = Request(url, body, {'Content-Type': self.headers.get_content_type()})
        try:
            with self.server.public_proxy.open(request, timeout=10) as upstream:
                record['upstreamStatus'] = upstream.status
                result = upstream.read(32 * 1024 + 1)
                content_type = upstream.headers.get('Content-Type', 'application/json')
        except HTTPError as error:
            record['upstreamStatus'] = error.code
            error.close()
            self.send_error(error.code)
            return
        except (URLError, TimeoutError):
            self.send_error(502)
            return
        if len(result) > 32 * 1024:
            self.send_error(502)
            return
        self.send_response(record['upstreamStatus'])
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(result)))
        self.end_headers()
        self.wfile.write(result)


@contextmanager
def browser(emulator):
    node = '/Applications/DevEco-Studio.app/Contents/tools/node/bin/node'
    fixture = Path(__file__).with_name('fixtures') / 'arkweb-evaluate.cjs'
    process = subprocess.Popen([node, str(fixture), str(approval['ws_module']())], stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE, text=True)
    def send(value, timeout=15):
        process.stdin.write(json.dumps(value)+'\n')
        process.stdin.flush()
        assert select.select([process.stdout], [], [], timeout)[0], 'ArkWeb diagnostic command timed out'
        reply = process.stdout.readline()
        assert reply, 'ArkWeb diagnostic channel closed'
        return json.loads(reply)
    try:
        assert send({'endpoint': emulator.url.replace('http:', 'ws:')+'/inspector/devtools/cdp',
                     'cookie': emulator.cookie()}) == {'ready': True}
        yield send
    finally:
        process.stdin.close()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.terminate()
            process.wait(timeout=3)
        process.stdout.close()


def wait(run, expression, label):
    deadline = time.monotonic()+20
    last = None
    while time.monotonic() < deadline:
        last = run(expression)
        if last:
            return last
        time.sleep(.25)
    raise AssertionError(f'ArkWeb did not render {label}: {last}')


def click(selector):
    return f'''(() => {{const button=document.querySelector({json.dumps(selector)});
        if (!button || !button.getClientRects().length) return false;
        button.click(); return true;}})()'''


def open_session(emulator, run, title):
    search_field = "[data-sidebar-workspace-header] input[type=text]"
    if not run(f'!!document.querySelector({json.dumps(search_field)})?.getClientRects().length'):
        ui['open_sidebar'](emulator)
    wait(run, f'''(() => {{
        const field=document.querySelector({json.dumps(search_field)});
        if (!field?.getClientRects().length) return false;
        const search=field.parentElement.querySelector('button[aria-expanded]');
        if (search?.getAttribute('aria-expanded') === 'false') search.click();
        if (field.value !== {json.dumps(title)}) {{
          Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(field, {json.dumps(title)});
          field.dispatchEvent(new Event('input',{{bubbles:true}}));
        }}
        const item=[...document.querySelectorAll('[data-sidebar-list-area] [role=treeitem]')].find(el =>
          el.getClientRects().length && el.textContent.includes({json.dumps(title)}));
        if (item) {{ item.click(); return true; }}
        return false;
    }})()''', 'the fixture session')


def open_reasoning(emulator, run, title, marker):
    open_session(emulator, run, title)
    wait(run, f'document.body.innerText.includes({json.dumps("The archive verification code is "+marker)})', 'the fixture conversation')
    wait(run, f'''(() => {{
        const row=document.querySelector({json.dumps(DISCLOSURE)});
        if (row?.getClientRects().length) return true;
        for (const button of document.querySelectorAll('[data-turn-process][aria-expanded=false], [data-process-activity][aria-expanded=false]'))
          if (button.getClientRects().length) button.click();
        return false;
    }})()''', 'the reasoning disclosure')
    wait(run, click(DISCLOSURE), 'reasoning expansion')


def check_body(run, state, text, view=None):
    return wait(run, f'''(() => {{
        const body=document.querySelector({json.dumps(BODY)});
        return body?.dataset.translationState === {json.dumps(state)}
          && (!{json.dumps(view)} || body.dataset.translationView === {json.dumps(view)})
          && body.textContent.includes({json.dumps(text)});
    }})()''', f'{state} translation')


def setting(emulator, provider, target):
    namespaces = emulator.rpc('settings/describe', {})['namespaces']
    row, = [row for row in namespaces if row['ns'] == 'cot-translation']
    params = {'ns': row['ns'], 'patch': {'provider': provider, 'targetLanguage': target}}
    emulator.rpc('settings/update', params)
    prefs = emulator.rpc('cotTranslation/limits', {})['preferences']
    assert prefs == params['patch'], prefs


def switch(emulator, name, enabled):
    result = emulator.rpc('pluginManager/setBundleEnabled', {'name': name, 'enabled': enabled})
    assert result['application'] in ['applied', 'restart-required'], result


def restart(emulator):
    emulator.stop()
    emulator.start()
    return emulator.ready('normal')


def verify_fixture(emulator, server, title, marker, session, evidence):
    original = support['events'](emulator, session)
    with browser(emulator) as run:
        assert not server.calls
        open_reasoning(emulator, run, title, marker)
        check_body(run, 'ready', FIXTURE_TRANSLATIONS['bing', 'zh-Hans'], 'translated')
        wait(run, click(BODY+' button'), 'show original')
        check_body(run, 'ready', SOURCE, 'original')
        wait(run, click(BODY+' button'), 'show translation')
        check_body(run, 'ready', FIXTURE_TRANSLATIONS['bing', 'zh-Hans'], 'translated')
        assert len(server.calls) == 1, server.calls
    evidence['originalAndTranslatedViews'] = True
    restart(emulator)
    with browser(emulator) as run:
        open_reasoning(emulator, run, title, marker)
        check_body(run, 'ready', FIXTURE_TRANSLATIONS['bing', 'zh-Hans'], 'translated')
        assert len(server.calls) == 1, server.calls
        server.fail = True
        setting(emulator, 'google', 'ja')
        check_body(run, 'failed', SOURCE, 'original')
        server.fail = False
        wait(run, click(BODY+' button:last-of-type'), 'translation retry')
        check_body(run, 'ready', FIXTURE_TRANSLATIONS['google', 'ja'], 'translated')
        server.hold = True
        setting(emulator, 'google', 'de')
        assert server.started.wait(10), 'No real provider request was held'
        switch(emulator, NAME, False)
        assert server.closed.wait(12), 'Disabling translation did not close its HTTP request'
        wait(run, f'!document.querySelector({json.dumps(BODY)})', 'translation controls to unmount')
    events = support['events'](emulator, session)
    assert events[:len(original)] == original
    appended = [row['type'] for row in events[len(original):]]
    assert set(appended) <= {'plugin:translator/request','plugin:translator/result','session/end-seed'}, appended
    assert appended.count('plugin:translator/result') == 2
    evidence['appendedEventTypes'] = appended
    expected = [('bing', 'zh-Hans'), ('google', 'ja'), ('google', 'ja'), ('google', 'de')]
    assert [(row['provider'],row['target']) for row in server.calls] == expected, server.calls
    assert all(row['requestShape'] and row['text']==SOURCE and not row['authorization'] and not row['cookie'] for row in server.calls)
    evidence.update(providerCalls=server.calls, persistedAcrossRestart=True, failureRetainedOriginal=True,
                    pendingRequestCancelledOnDisable=True, originalConversationUnchanged=True)


def verify_paid_arkweb(emulator, title, marker, session, evidence):
    with browser(emulator) as run:
        open_reasoning(emulator, run, title, marker)
        translation = wait(run, f'''(() => {{
            const body=document.querySelector({json.dumps(BODY)});
            const text=body && Array.from(body.children).slice(1).map(node => node.textContent).join('').trim();
            return body?.dataset.translationState === 'ready' &&
                body.dataset.translationView === 'translated' && /[\u4e00-\u9fff]/.test(text ?? '') && text;
        }})()''', 'a live Chinese translation')
        wait(run, click(BODY+' button'), 'show the original for the live translation')
        check_body(run, 'ready', SOURCE, 'original')
        wait(run, click(BODY+' button'), 'show the live translation')
        check_body(run, 'ready', translation, 'translated')
    rows = [row for row in support['events'](emulator,session) if row['type'].startswith('plugin:translator/')]
    assert [row['type'] for row in rows]==['plugin:translator/request','plugin:translator/result'],rows
    paid = rows[0]['data']['metadata']['modelRequest']
    assert rows[0]['data']['provider']=='deepseek-official'
    assert paid['config']['model']=='deepseek-flash' and paid['config']['reasoningEffort']=='off',paid['config']
    assert paid['messages']==[{'role':'user','content':[{'type':'text','text':SOURCE}]}]
    evidence['liveArkWebTranslation']=translation
    evidence['isolatedFlashRequest']={'model':'deepseek-flash','reasoningEffort':'off','messages':1}
    return rows


def run(emulator, output, live, arkweb_live=False):
    fixture = 'mh-cot-' + uuid.uuid4().hex[:10]
    folder = 'alpine/workspace-native/'+fixture
    remote = '/data/local/tmp/'+fixture
    evidence = {}
    originals = {}
    sessions = []
    workspace = None
    server = None
    reverse = None
    try:
        emulator.ready('normal')
        files = [PROFILE+'/'+name for name in ['package.json','pnpm-lock.yaml','cordis.patch.yml']]+['mobile-harness-boot.json']
        if live == 'profile-proxy':
            files.append(HARNESS_ENV)
        originals = {file:profile_bytes(emulator,file) for file in files}
        catalog = market['catalog'](emulator, NAME)
        assert catalog and catalog['optional'] and catalog['official'] and not catalog['enabled'], catalog
        evidence['defaultCatalog'] = {key:catalog[key] for key in ['enabled','version','availability']}
        for name in [flow['BUNDLE'],inspector['NAME'], NAME]:
            assert not market['catalog'](emulator,name)['enabled']
            switch(emulator,name,True)
        if not live or live in {'public-proxy', 'profile-proxy'}:
            if live == 'profile-proxy':
                server = ThreadingHTTPServer(('127.0.0.1',0),ConnectProxy)
                server.upstream = proxy_endpoint()
            else:
                server = ThreadingHTTPServer(('127.0.0.1',0),Provider)
                server.public_proxy = public_proxy() if live == 'public-proxy' else None
            server.calls, server.fail, server.hold = [], False, False
            server.started, server.closed = threading.Event(), threading.Event()
            threading.Thread(target=server.serve_forever,daemon=True).start()
            candidate = (f'tcp:{SERVER_PORT}', f'tcp:{server.server_port}')
            assert 'Forwardport result:OK' in emulator.hdc('rport',*candidate)
            reverse = candidate
            base = f'http://127.0.0.1:{SERVER_PORT}'
            emulator.stop()
            if live == 'profile-proxy':
                env = (originals[HARNESS_ENV] or b'').rstrip()
                assert not any(name in env.lower() for name in (b'http_proxy', b'https_proxy', b'all_proxy', b'no_proxy'))
                env += f'\nHTTPS_PROXY={base}\n'.encode()
                lsp['restore_bytes'](emulator,HARNESS_ENV,env,remote+'-env')
            else:
                config = {'bingEndpoint':base+'/bing','googleEndpoint':base+'/google','timeoutMs':30000}
                patch = originals[PROFILE+'/cordis.patch.yml'].rstrip()
                if patch == b'[]' or patch.endswith(b'\n[]'):
                    patch = patch[:-2].rstrip()
                patch += ('\n- id: translator\n  config: '+json.dumps(config)+'\n').encode()
                lsp['restore_bytes'](emulator,PROFILE+'/cordis.patch.yml',patch,remote+'-translator')
            emulator.start()
            emulator.ready('normal')
        else:
            restart(emulator)
        with support['model_key'](emulator):
            emulator.app('mkdir '+folder)
            item = emulator.rpc('workspace/create',{'request':{'path':support['WORKSPACE']+'/'+fixture}})
            assert item['created'], item
            workspace = item['workspace']['workspaceId']
            title = 'Translation sample '+fixture
            archive = flow['archive_bytes'](fixture,flow['SOURCE_PNG'].read_bytes(),text_title=title)
            status, lines = flow['upload'](emulator, workspace, archive)
            assert status == 200 and lines[-1]['outcome']['ok'], (status,lines)
            sessions.extend(lines[-1]['outcome']['value']['sessionIds'])
            session = sessions[0]
            emulator.rpc('session/selectModel', {'request': {'sessionId':session, **flow['MODEL']}})
            limits = emulator.rpc('cotTranslation/limits',{})
            assert limits['preferences']=={'provider':'bing','targetLanguage':'auto'}, limits
            evidence['availableProviders'] = limits['availableProviders']
            setting(emulator,'bing','zh')
            if arkweb_live:
                assert 'deepseek-official' in limits['availableProviders'],limits
                setting(emulator,'deepseek-official','zh')
                restart(emulator)
                paid_rows=verify_paid_arkweb(emulator,title,fixture,session,evidence)
            elif live in {'public-proxy', 'profile-proxy'}:
                evidence['publicTranslations'] = {}
                evidence['publicRequests'] = server.calls
                for provider in PUBLIC_ENDPOINTS:
                    assert provider in limits['availableProviders']
                    setting(emulator, provider, 'zh')
                    translated = emulator.rpc('cotTranslation/translate', {'request': {
                        'text': SOURCE, 'sessionId': session, 'provider': provider, 'targetLanguage': 'zh',
                    }}, timeout=40)
                    assert translated != SOURCE and any('\u4e00' <= char <= '\u9fff' for char in translated)
                    evidence['publicTranslations'][provider] = translated
                if live == 'profile-proxy':
                    assert {row['authority'] for row in server.calls} == ConnectProxy.authorities
                    assert all(row.get('connectStatus') == 200 for row in server.calls)
                    evidence['officialProviderEndpointsUnmodified'] = True
                else:
                    assert [(row['provider'], row.get('upstreamStatus')) for row in server.calls] == [('bing', 200), ('google', 200)]
                rows = [row for row in support['events'](emulator,session) if row['type'].startswith('plugin:translator/')]
                assert [row['type'].split('/')[-1] for row in rows] == ['request', 'result', 'request', 'result']
                assert [row['data']['provider'] for row in rows if row['type'].endswith('/request')] == list(PUBLIC_ENDPOINTS)
                restart(emulator)
                assert [row for row in support['events'](emulator,session) if row['type'].startswith('plugin:translator/')] == rows
                if live == 'public-proxy':
                    assert len(server.calls) == 2
                evidence['publicTranslationRecordsRestored'] = True
            elif live:
                assert live in limits['availableProviders'], limits
                setting(emulator,live,'zh')
                evidence['selectedLiveProvider'] = live
                try:
                    translation = emulator.rpc('cotTranslation/translate',{
                        'request':{'text':SOURCE,'sessionId':session,'provider':live,'targetLanguage':'zh'},
                    },timeout=70)
                except RuntimeError:
                    evidence['recordsAfterFailure'] = [row['type'] for row in support['events'](emulator,session)
                                                       if row['type'].startswith('plugin:translator/')]
                    raise
                assert translation != SOURCE and any('\u4e00' <= char <= '\u9fff' for char in translation), translation
                evidence['liveTranslation'] = translation
                if live == 'deepseek-official':
                    paid, = [row['data']['metadata']['modelRequest'] for row in support['events'](emulator,session)
                             if row['type']=='plugin:translator/request' and row['data']['provider']=='deepseek-official']
                    assert paid['config']['model']=='deepseek-flash' and paid['config']['reasoningEffort']=='off', paid['config']
                    assert paid['messages']==[{'role':'user','content':[{'type':'text','text':SOURCE}]}]
                    evidence['isolatedFlashRequest'] = {'model':'deepseek-flash','reasoningEffort':'off','messages':1}
            else:
                restart(emulator)
                verify_fixture(emulator,server,title,fixture,session,evidence)
        if arkweb_live:
            restart(emulator)
            with browser(emulator) as run:
                open_reasoning(emulator,run,title,fixture)
                check_body(run,'ready',evidence['liveArkWebTranslation'],'translated')
            restored=[row for row in support['events'](emulator,session)
                      if row['type'].startswith('plugin:translator/')]
            assert restored==paid_rows,restored
            evidence['translationReopenedWithoutCredential']=True
            evidence['noAdditionalTranslationAfterRestart']=True
    finally:
        try:
            for session in sessions:
                emulator.rpc('workspace/archiveSession',{'request':{'sessionId':session}})
            if workspace is not None:
                assert emulator.rpc('workspace/delete',{'request':{'workspaceId':workspace}})=={'deleted':True}
        finally:
            try:
                if originals:
                    emulator.stop()
                    emulator.app('rm -rf '+folder)
                    for i,(file,body) in enumerate(originals.items()):
                        if body is None:
                            emulator.app('rm -f '+file)
                        else:
                            lsp['restore_bytes'](emulator,file,body,remote+str(i))
                    emulator.start()
                    evidence['restoredReadyMs'] = emulator.ready('normal')
                    assert all(profile_bytes(emulator,file)==body for file,body in originals.items())
                    evidence['restoredHashes']={file:hashlib.sha256(body).hexdigest() if body is not None else None
                                                for file,body in originals.items()}
            finally:
                if reverse:
                    emulator.hdc('fport','rm',*reverse)
                if server:
                    server.shutdown()
                    server.server_close()
                output.write_text(json.dumps(evidence,ensure_ascii=False,indent=2)+'\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('target')
    parser.add_argument('output',type=Path)
    parser.add_argument('--live',choices=['bing','google','deepseek-official','public-proxy','profile-proxy'],
                        help='Use real providers. profile-proxy tests the original Bing and Google endpoints with HTTPS_PROXY in the app-owned environment.')
    parser.add_argument('--arkweb-live',action='store_true',help='Drive the selected DeepSeek Flash provider through ArkWeb')
    parser.add_argument('--host-port', type=int, default=19643)
    args = parser.parse_args()
    if args.arkweb_live and args.live!='deepseek-official':
        parser.error('--arkweb-live requires --live deepseek-official')
    if not os.environ.get('MH_TEST_DEEPSEEK_API_KEY'):
        parser.error('MH_TEST_DEEPSEEK_API_KEY is required for the configured ArkWeb fixture')
    emulator = support['Emulator'](args.target,args.host_port)
    forward = (f'tcp:{args.host_port}','tcp:19592')
    assert 'Forwardport result:OK' in emulator.hdc('fport',*forward)
    try:
        run(emulator,args.output,args.live,args.arkweb_live)
    finally:
        emulator.hdc('fport','rm',*forward)
