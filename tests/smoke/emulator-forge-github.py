"""Exercise the shipped GitHub CLI and official Forge RPCs over an owned TLS fixture."""
import argparse
import json
from pathlib import Path
import runpy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import select
import socket
import ssl
import subprocess
import tempfile
import threading
from urllib.parse import parse_qs, urlsplit
import uuid

flow = runpy.run_path(str(Path(__file__).with_name('emulator-worktree-restore.py')))
support, agent, lsp = (flow[key] for key in ['support', 'agent', 'lsp'])
TOKEN = 'owned-harmony-forge-fixture'
HEAD = 'a'*40
BASE = 'b'*40
SECOND = 'c'*40
TEXT = 'Owned Forge contents transported using the packaged gh CLI.'
HOST = 'forge-fixture.test'
URL = 'https://'+HOST+'/fixture/mobile/pull/7'
CA_BUNDLE = 'alpine/etc/ssl/certs/ca-certificates.crt'
GH_CONFIG = 'alpine/native-benchmark-home/.config/gh'


class GitHubFixture(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def reply(self, status, payload, content_type='application/json'):
        body = json.dumps(payload).encode() if content_type == 'application/json' else payload.encode()
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def authenticated(self):
        return self.headers.get('Authorization') in ('token '+TOKEN, 'Bearer '+TOKEN)

    def do_GET(self):
        url = urlsplit(self.path)
        auth = self.authenticated()
        self.server.calls.append({'method': 'GET', 'path': url.path, 'authenticated': auth})
        if not auth:
            self.reply(401, {'message': 'Bad credentials'})
        elif (url.path == '/api/v3/repos/fixture/mobile/contents/fixture.txt'
              and parse_qs(url.query) == {'ref': [HEAD]}
              and self.headers.get('Accept') == 'application/vnd.github.raw+json'):
            self.reply(200, TEXT+'\n', 'text/plain')
        else:
            self.reply(404, {'message': 'Fixture route not found'})

    def do_POST(self):
        auth = self.authenticated()
        query = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        values = query.get('variables', {})
        cursor = values.get('cursor')
        self.server.calls.append({'method': 'POST', 'path': self.path, 'authenticated': auth, 'cursor': cursor})
        if not auth:
            self.reply(401, {'message': 'Bad credentials'})
            return
        if (self.path != '/api/graphql' or 'commits(first:' not in query.get('query', '')
                or [values.get(key) for key in ['owner', 'name', 'number']] != ['fixture', 'mobile', 7]
                or cursor not in [None, 'next']):
            self.reply(400, {'message': 'Unexpected fixture GraphQL request'})
            return
        sha, parent, title = (SECOND, BASE, 'First commit') if cursor is None else (HEAD, SECOND, 'Second commit')
        commits = {'totalCount': 2, 'pageInfo': {'hasNextPage': cursor is None,
                   'endCursor': 'next' if cursor is None else None}, 'nodes': [{'commit': {
                        'oid': sha, 'messageHeadline': title, 'authoredDate': '2026-01-01T00:00:00Z',
                        'author': {'name': 'Fixture', 'user': None}, 'parents': {'nodes': [{'oid': parent}]}},
                   }]}
        self.reply(200, {'data': {'repository': {'pullRequest': {'headRefOid': HEAD, 'commits': commits}}}})


class ConnectProxy(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def do_CONNECT(self):
        if self.path != HOST+':443':
            self.send_error(403)
            return
        with socket.create_connection(('127.0.0.1',self.server.destination),timeout=5) as upstream:
            self.send_response(200)
            self.end_headers()
            self.close_connection = True
            while True:
                readable, _, _ = select.select([self.connection,upstream],[],[],5)
                if not readable:
                    return
                for stream in readable:
                    data = stream.recv(65536)
                    if not data:
                        return
                    target = upstream if stream is self.connection else self.connection
                    target.sendall(data)


def make_tls(folder):
    conf = folder/'cert.conf'
    conf.write_text('[req]\ndistinguished_name=dn\nx509_extensions=extensions\nprompt=no\n'
                    '[dn]\nCN=Mobile Harness Forge fixture\n[extensions]\nsubjectAltName=DNS:'+HOST+'\n'
                    'basicConstraints=critical,CA:TRUE\nkeyUsage=critical,digitalSignature,keyEncipherment,keyCertSign\n')
    key, cert = folder/'fixture.key', folder/'fixture.pem'
    subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-days','1','-config',str(conf),
                    '-keyout',str(key),'-out',str(cert)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert, key)
    return context, cert.read_bytes()


def run(device, output):
    evidence = {}
    cases = ['package.json', 'pnpm-lock.yaml', 'cordis.patch.yml']
    original = {}
    ident = 'mh-forge-github-'+uuid.uuid4().hex[:10]
    folder = 'alpine/workspace-native/'+ident
    remote = '/data/local/tmp/'+ident
    forward = ('tcp:19643', 'tcp:19592')
    reverse = None
    server = None
    proxy = None
    workspace, sid = None, None
    profile = flow['PROFILE']
    owns_config = False
    assert 'Forwardport result:OK' in device.hdc('fport', *forward)
    try:
        device.ready('normal')
        assert device.app('test ! -e '+GH_CONFIG+' && printf EMPTY') == 'EMPTY'
        original = {path: agent['read_bytes'](device,path) for path in
                    [profile+'/'+case for case in cases]+['mobile-harness-boot.json', CA_BUNDLE]}
        with tempfile.TemporaryDirectory(prefix=ident) as temp:
            context, certificate = make_tls(Path(temp))
            server = ThreadingHTTPServer(('127.0.0.1',0),GitHubFixture)
            server.socket = context.wrap_socket(server.socket, server_side=True)
            server.calls = []
            threading.Thread(target=server.serve_forever,daemon=True).start()
            proxy = ThreadingHTTPServer(('127.0.0.1',0),ConnectProxy)
            proxy.destination = server.server_port
            threading.Thread(target=proxy.serve_forever,daemon=True).start()
            target = ('tcp:19772',f'tcp:{proxy.server_port}')
            answer = device.hdc('rport',*target)
            assert 'Forwardport result:OK' in answer, answer
            reverse = target
            enabled = device.rpc('pluginManager/setBundleEnabled', {'name': flow['FORGE'], 'enabled': True})
            assert enabled['application'] in ['applied','restart-required'], enabled
            current = agent['read_bytes'](device,profile+'/cordis.patch.yml')
            module = 'file://'+support['WORKSPACE']+'/'+ident+'/proxy.mjs'
            patch = current.rstrip()+(
                '\n- id: forge-github\n  config:\n    hosts: ["'+HOST+'"]\n'
                '- insert:\n    - id: '+ident+'\n      name: "'+module+'"\n').encode()
            device.stop()
            lsp['restore_bytes'](device,profile+'/cordis.patch.yml',patch,remote+'-profile')
            lsp['restore_bytes'](device,CA_BUNDLE,original[CA_BUNDLE]+b'\n'+certificate,remote+'-cert')
            device.app('mkdir -p '+folder+' '+GH_CONFIG)
            owns_config=True
            source = b'export function apply() { process.env.HTTPS_PROXY = "http://127.0.0.1:19772"; }\n'
            lsp['restore_bytes'](device,folder+'/proxy.mjs',source,remote+'-proxy')
            config = HOST+':\n  user: fixture\n  oauth_token: '+TOKEN+'\n  git_protocol: https\n'
            lsp['restore_bytes'](device,GH_CONFIG+'/hosts.yml',config.encode(),remote+'-hosts')
            device.start()
            device.ready('normal')
            registered = device.rpc('workspace/create',{'request':{'path':support['WORKSPACE']+'/'+ident}})
            assert registered['created']
            workspace = registered['workspace']['workspaceId']
            sid = device.rpc('session/create',{'request':{'workspaceId':workspace}})['sessionId']
            device.rpc('forgePanel/track',{'sessionId':sid,'url':URL})
            response = device.rpc('forgePanel/changeRequestText',
                                  {'sessionId':sid,'url':URL,'commit':HEAD,'path':'fixture.txt'})
            assert response==TEXT,response
            evidence['rawFileAtCommit']=True
            commits = device.rpc('forgePanel/changeRequestCommits',{'sessionId':sid,'url':URL})
            assert commits['headSha']==HEAD and not commits['truncated'],commits
            assert [commit['sha'] for commit in commits['commits']]==[SECOND,HEAD],commits
            assert [commit['parent'] for commit in commits['commits']]==[BASE,SECOND],commits
            evidence['paginatedCommitGraph']=commits
            assert all(row['authenticated'] for row in server.calls),server.calls
    finally:
        try:
            try:
                if sid:
                    device.rpc('workspace/archiveSession',{'request':{'sessionId':sid}})
                if workspace:
                    device.rpc('workspace/delete',{'request':{'workspaceId':workspace}})
            finally:
                if original:
                    device.stop()
                    device.app('rm -rf '+folder)
                    if owns_config:
                        device.app('rm -rf '+GH_CONFIG)
                    for i,(path,body) in enumerate(original.items()):
                        lsp['restore_bytes'](device,path,body,remote+'-restore-'+str(i))
                    device.start()
                    evidence['restoredReadyMs']=device.ready('normal')
                    assert all(agent['read_bytes'](device,path)==body for path,body in original.items())
                    evidence['configAndCABytesRestored']=True
        finally:
            if reverse:
                device.hdc('fport','rm',*reverse)
            device.hdc('fport','rm',*forward)
            if proxy:
                proxy.shutdown()
                proxy.server_close()
            if server:
                server.shutdown()
                server.server_close()
                evidence['requests']=server.calls
            output.write_text(json.dumps(evidence,indent=2)+'\n')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('target')
    parser.add_argument('output',type=Path)
    args=parser.parse_args()
    run(support['Emulator'](args.target,19643),args.output)
