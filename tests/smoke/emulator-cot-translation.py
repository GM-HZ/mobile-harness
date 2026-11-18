"""Exercise the optional translation bundle in the actual Phone ArkWeb client."""
import argparse
from contextlib import contextmanager
import hashlib
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
from urllib.parse import parse_qs, urlsplit
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


class Provider(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_POST(self):
        url = urlsplit(self.path)
        provider = url.path.strip('/')
        body = self.rfile.read(int(self.headers['Content-Length']))
        params = parse_qs(url.query)
        if provider == 'bing':
            text, = json.loads(body)
            target, = params['to']
            shape = params == {'to': [target], 'isEnterpriseClient': ['false']} and self.headers.get_content_type() == 'application/json'
        else:
            assert provider == 'google'
            form = parse_qs(body.decode())
            text, = form['q']
            target, = form['tl']
            shape = not params and form == {'q': [SOURCE], 'tl': [target], 'sl': ['auto'], 'client': ['gtx'], 'dt': ['t']}
            shape = shape and self.headers.get_content_type() == 'application/x-www-form-urlencoded'
        self.server.calls.append({'provider': provider, 'target': target, 'text': text, 'requestShape': shape,
                                  'authorization': bool(self.headers.get('Authorization')), 'cookie': bool(self.headers.get('Cookie'))})
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


def open_reasoning(emulator, run, title):
    ui['open_sidebar'](emulator)
    wait(run, f'''(() => {{
        const field=document.querySelector('[data-sidebar-workspace-header] input[type=text]');
        if (!field?.getClientRects().length) return false;
        const search=field.parentElement.querySelector('button[aria-expanded]');
        if (search?.getAttribute('aria-expanded') === 'false') search.click();
        if (field.value !== {json.dumps(title)}) {{
          Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(field, {json.dumps(title)});
          field.dispatchEvent(new Event('input',{{bubbles:true}}));
        }}
        const item=[...document.querySelectorAll('[role=treeitem]')].find(el =>
          el.getClientRects().length && el.textContent.includes({json.dumps(title)}));
        if (item) {{ item.click(); return true; }}
        return false;
    }})()''', 'the fixture session')
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


def verify_fixture(emulator, server, title, session, evidence):
    original = support['events'](emulator, session)
    with browser(emulator) as run:
        assert not server.calls
        open_reasoning(emulator, run, title)
        check_body(run, 'ready', FIXTURE_TRANSLATIONS['bing', 'zh-Hans'], 'translated')
        wait(run, click(BODY+' button'), 'show original')
        check_body(run, 'ready', SOURCE, 'original')
        wait(run, click(BODY+' button'), 'show translation')
        check_body(run, 'ready', FIXTURE_TRANSLATIONS['bing', 'zh-Hans'], 'translated')
        assert len(server.calls) == 1, server.calls
    evidence['originalAndTranslatedViews'] = True
    restart(emulator)
    with browser(emulator) as run:
        open_reasoning(emulator, run, title)
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
    assert [row for row in events if not row['type'].startswith('plugin:translator/')] == original
    assert sum(row['type']=='plugin:translator/result' for row in events)==2
    evidence['persistedRecordTypes'] = [row['type'] for row in events if row['type'].startswith('plugin:translator/')]
    expected = [('bing', 'zh-Hans'), ('google', 'ja'), ('google', 'ja'), ('google', 'de')]
    assert [(row['provider'],row['target']) for row in server.calls] == expected, server.calls
    assert all(row['requestShape'] and row['text']==SOURCE and not row['authorization'] and not row['cookie'] for row in server.calls)
    evidence.update(providerCalls=server.calls, persistedAcrossRestart=True, failureRetainedOriginal=True,
                    pendingRequestCancelledOnDisable=True, originalConversationUnchanged=True)


def run(emulator, output, live):
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
        originals = {file:agent['read_bytes'](emulator,file) for file in files}
        catalog = market['catalog'](emulator, NAME)
        assert catalog and catalog['optional'] and catalog['official'] and not catalog['enabled'], catalog
        evidence['defaultCatalog'] = {key:catalog[key] for key in ['enabled','version','availability']}
        for name in [flow['BUNDLE'],inspector['NAME'], NAME]:
            assert not market['catalog'](emulator,name)['enabled']
            switch(emulator,name,True)
        if not live:
            server = ThreadingHTTPServer(('127.0.0.1',0),Provider)
            server.calls, server.fail, server.hold = [], False, False
            server.started, server.closed = threading.Event(), threading.Event()
            threading.Thread(target=server.serve_forever,daemon=True).start()
            candidate = (f'tcp:{SERVER_PORT}', f'tcp:{server.server_port}')
            assert 'Forwardport result:OK' in emulator.hdc('rport',*candidate)
            reverse = candidate
            base = f'http://127.0.0.1:{SERVER_PORT}'
            config = {'bingEndpoint':base+'/bing','googleEndpoint':base+'/google','timeoutMs':30000}
            patch = originals[PROFILE+'/cordis.patch.yml'].rstrip()+('\n- id: translator\n  config: '+json.dumps(config)+'\n').encode()
            emulator.stop()
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
            archive = flow['archive_bytes'](fixture,flow['SOURCE_PNG'].read_bytes(),text_title=fixture)
            status, lines = flow['upload'](emulator, workspace, archive)
            assert status == 200 and lines[-1]['outcome']['ok'], (status,lines)
            sessions.extend(lines[-1]['outcome']['value']['sessionIds'])
            session = sessions[0]
            limits = emulator.rpc('cotTranslation/limits',{})
            assert limits['preferences']=={'provider':'bing','targetLanguage':'auto'}, limits
            evidence['availableProviders'] = limits['availableProviders']
            setting(emulator,'bing','zh')
            if live:
                evidence['liveTranslations'] = {}
                for provider in ['bing', 'deepseek-official']:
                    assert provider in limits['availableProviders'], limits
                    setting(emulator,provider,'zh')
                    translation = emulator.rpc('cotTranslation/translate',{
                        'request':{'text':SOURCE,'sessionId':session,'provider':provider,'targetLanguage':'zh'},
                    },timeout=70)
                    assert translation != SOURCE and any('\u4e00' <= char <= '\u9fff' for char in translation), translation
                    evidence['liveTranslations'][provider] = translation
                paid, = [row['data']['metadata']['modelRequest'] for row in support['events'](emulator,session)
                         if row['type']=='plugin:translator/request' and row['data']['provider']=='deepseek-official']
                assert paid['config']['model']=='deepseek-flash' and paid['config']['reasoningEffort']=='off', paid['config']
                assert paid['messages']==[{'role':'user','content':[{'type':'text','text':SOURCE}]}]
                evidence['isolatedFlashRequest'] = {'model':'deepseek-flash','reasoningEffort':'off','messages':1}
            else:
                restart(emulator)
                verify_fixture(emulator,server,fixture,session,evidence)
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
                        lsp['restore_bytes'](emulator,file,body,remote+str(i))
                    emulator.start()
                    evidence['restoredReadyMs'] = emulator.ready('normal')
                    assert all(agent['read_bytes'](emulator,file)==body for file,body in originals.items())
                    evidence['restoredHashes']={file:hashlib.sha256(body).hexdigest() for file,body in originals.items()}
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
    parser.add_argument('--live',action='store_true',help='Use real Bing and configured DeepSeek Flash with the synthetic fixture')
    args = parser.parse_args()
    if not os.environ.get('MH_TEST_DEEPSEEK_API_KEY'):
        parser.error('MH_TEST_DEEPSEEK_API_KEY is required for the configured ArkWeb fixture')
    emulator = support['Emulator'](args.target,19643)
    forward = ('tcp:19643','tcp:19592')
    assert 'Forwardport result:OK' in emulator.hdc('fport',*forward)
    try:
        run(emulator,args.output,args.live)
    finally:
        emulator.hdc('fport','rm',*forward)
