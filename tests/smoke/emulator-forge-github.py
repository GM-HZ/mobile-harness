"""Exercise the shipped GitHub CLI and official Forge RPCs over an owned TLS fixture."""
import argparse
import hashlib
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
PUBLIC_REPO = 'GM-HZ/omnix'
PUBLIC_PULL = 9
PUBLIC_PATH = 'codex-rs/codex-api/src/chat_completions/types.rs'
FORGE_SOURCE = Path(__file__).resolve().parents[2] / 'vendor/repos/dsh/packages/experimental/forge-github/src'
PULL = '/api/v3/repos/fixture/mobile/pulls/7'
REVIEW_BODY = "Owned review with 'quotes', a second line, and 中文.\nKeep the file change."
INLINE = {'path': 'fixture.txt', 'side': 'R', 'startLine': 2, 'endLine': 3, 'body': 'Check lines 2–3.'}
REVIEW_PAYLOAD = {
    'commit_id': HEAD, 'event': 'COMMENT', 'body': REVIEW_BODY,
    'comments': [{'path': 'fixture.txt', 'side': 'RIGHT', 'start_side': 'RIGHT',
                  'start_line': 2, 'line': 3, 'body': INLINE['body']}],
}
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
        elif url.path == PULL:
            self.reply(200, {'head': {'sha': HEAD}, 'state': 'closed' if self.server.merged else 'open'})
        elif (url.path == '/api/v3/repos/fixture/mobile/contents/fixture.txt'
              and parse_qs(url.query) == {'ref': [HEAD]}
              and self.headers.get('Accept') == 'application/vnd.github.raw+json'):
            self.reply(200, TEXT+'\n', 'text/plain')
        else:
            self.reply(404, {'message': 'Fixture route not found'})

    def read_json(self):
        if self.headers.get('Transfer-Encoding', '').lower() == 'chunked':
            body = bytearray()
            while True:
                size = int(self.rfile.readline(64).split(b';', 1)[0], 16)
                if not size:
                    assert self.rfile.readline(64) == b'\r\n'
                    return json.loads(body)
                assert len(body) + size <= 65_536
                body.extend(self.rfile.read(size))
                assert self.rfile.read(2) == b'\r\n'
        return json.loads(self.rfile.read(int(self.headers['Content-Length'])))

    def do_PUT(self):
        auth = self.authenticated()
        body = self.read_json()
        self.server.calls.append({'method': 'PUT', 'path': self.path, 'authenticated': auth, 'body': body})
        if not auth:
            self.reply(401, {'message': 'Bad credentials'})
        elif self.path != PULL + '/merge' or body.get('merge_method') != 'squash':
            self.reply(400, {'message': 'Unexpected fixture merge'})
        elif body.get('sha') != HEAD:
            self.reply(409, {'message': 'The supplied head SHA does not match'})
        elif self.server.merged:
            self.reply(405, {'message': 'Pull request already merged'})
        else:
            self.server.merged = True
            self.reply(200, {'sha': 'd'*40, 'merged': True, 'message': 'Fixture merged'})

    def do_POST(self):
        auth = self.authenticated()
        query = self.read_json()
        if self.path == PULL + '/reviews':
            self.server.calls.append({'method': 'POST', 'path': self.path, 'authenticated': auth, 'body': query})
            if not auth:
                self.reply(401, {'message': 'Bad credentials'})
            elif self.server.review_mode == 'refuse':
                self.reply(403, {'message': 'Review permission denied by fixture'})
            elif query != REVIEW_PAYLOAD:
                self.reply(422, {'message': 'Review JSON was not preserved'})
            else:
                self.server.reviews.append(query)
                if self.server.review_mode == 'uncertain':
                    self.reply(503, {'message': 'Receipt unavailable after fixture recorded review'})
                else:
                    self.reply(200, {'html_url': URL + '#pullrequestreview-1'})
            return
        document = query.get('query', '')
        values = query.get('variables', {})
        cursor = values.get('cursor')
        self.server.calls.append({'method': 'POST', 'path': self.path, 'authenticated': auth, 'cursor': cursor})
        if not auth:
            self.reply(401, {'message': 'Bad credentials'})
            return
        if self.path != '/api/graphql':
            self.reply(404, {'message': 'Fixture route not found'})
            return
        if 'u0: user(login: $u0)' in document and values == {'u0': 'fixture-reviewer'}:
            self.reply(200, {'data': {'u0': {'id': 'U_fixture'}}})
            return
        if 'requestReviews(input:' in document:
            expected = {'input': {'pullRequestId': 'PR_fixture', 'union': True, 'userIds': ['U_fixture']}}
            if values != expected:
                self.reply(422, {'message': 'Reviewer mutation variables were not preserved'})
                return
            self.server.requested_reviews.append(values)
            self.reply(200, {'data': {'requestReviews': {'clientMutationId': None}}})
            return
        if [values.get(key) for key in ['owner', 'name', 'number']] != ['fixture', 'mobile', 7]:
            self.reply(400, {'message': 'Unexpected fixture GraphQL reference'})
            return
        if '{ id headRefOid }' in document:
            self.reply(200, {'data': {'repository': {'pullRequest': {'id': 'PR_fixture', 'headRefOid': HEAD}}}})
            return
        if 'commits(first:' not in document or cursor not in [None, 'next']:
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
        if self.path not in {host + ':443' for host in getattr(self.server, 'hosts', (HOST,))}:
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
                    try:
                        data = stream.recv(65536)
                        if not data:
                            return
                        target = upstream if stream is self.connection else self.connection
                        target.sendall(data)
                    except (BrokenPipeError, ConnectionResetError):
                        return


def github_api(*args, body=None):
    return subprocess.check_output(['gh', 'api', '--hostname', 'github.com', *args],
                                   input=body, timeout=25, stderr=subprocess.DEVNULL)


def saved_file(device, path):
    if device.app('test -f '+path+' && printf PRESENT') == 'PRESENT':
        return agent['read_bytes'](device, path)
    return None


class PublicPullFixture(GitHubFixture):
    """Forward exactly two read operations, with credentials kept on the desktop."""

    def do_GET(self):
        path = '/api/v3/' + self.server.contents
        if not self.authenticated() or self.path != path:
            self.reply(403, {'message': 'Path is outside the public read fixture'})
            return
        if self.headers.get('Accept') != 'application/vnd.github.raw+json':
            self.reply(400, {'message': 'Expected the GitHub raw contents media type'})
            return
        try:
            content = github_api('-H', 'Accept: application/vnd.github.raw+json', self.server.contents)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            self.reply(502, {'message': 'GitHub contents request failed'})
            return
        self.server.calls.append({'operation': 'contents', 'status': 200,
                                  'sha256': hashlib.sha256(content).hexdigest()})
        self.reply(200, content.decode(), 'text/plain')

    def do_POST(self):
        if not self.authenticated() or self.path != '/api/graphql':
            self.reply(403, {'message': 'GraphQL path is outside the public read fixture'})
            return
        query = self.read_json()
        variables = query.get('variables', {})
        owner, repo = PUBLIC_REPO.split('/')
        if (query.get('query') != self.server.commits_query or
            set(variables) != {'owner', 'name', 'number', 'first'} or
            variables['owner'].casefold() != owner.casefold() or variables['name'] != repo or
            variables['number'] != PUBLIC_PULL or not 1 <= variables['first'] <= 100):
            self.reply(403, {'message': 'Only the fixed public pull request commit query is allowed'})
            return
        try:
            response = json.loads(github_api('graphql', '--input', '-', body=json.dumps(query).encode()))
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            self.reply(502, {'message': 'GitHub commit query failed'})
            return
        self.server.calls.append({'operation': 'commits', 'status': 200})
        self.reply(200, response)

    def do_PUT(self):
        self.reply(403, {'message': 'The public read fixture forbids writes'})


def verify_public_read(device, server, sid):
    official = json.loads(github_api(f'repos/{PUBLIC_REPO}/pulls/{PUBLIC_PULL}'))
    head = official['head']['sha']
    reference_commits = json.loads(github_api(f'repos/{PUBLIC_REPO}/pulls/{PUBLIC_PULL}/commits'))
    assert len(reference_commits) == official['commits'] and len(reference_commits) < 30
    server.contents = f'repos/{PUBLIC_REPO}/contents/{PUBLIC_PATH}?ref={head}'
    server.commits_query = (FORGE_SOURCE/'commits.ts').read_text().split(
        'export const COMMITS_QUERY = `', 1)[1].split('`', 1)[0]
    exact_content = github_api('-H', 'Accept: application/vnd.github.raw+json', server.contents)
    proxy_url = f'https://{HOST}/{PUBLIC_REPO}/pull/{PUBLIC_PULL}'
    args = {'sessionId': sid, 'url': proxy_url}
    device.rpc('forgePanel/track', args)
    response = device.rpc('forgePanel/changeRequestText', {**args, 'commit': head, 'path': PUBLIC_PATH})
    assert response == exact_content.decode().removesuffix('\n').removesuffix('\r')
    graph = device.rpc('forgePanel/changeRequestCommits', args)
    assert graph['headSha'] == head and not graph['truncated']
    assert [commit['sha'] for commit in graph['commits']] == [commit['sha'] for commit in reference_commits]
    assert [commit['parent'] for commit in graph['commits']] == [
        commit['parents'][0]['sha'] if commit['parents'] else None for commit in reference_commits]
    assert {call['operation'] for call in server.calls} == {'contents', 'commits'}, server.calls
    return {'pullRequest': official['html_url'], 'headSha': head, 'path': PUBLIC_PATH,
            'contentSha256': hashlib.sha256(exact_content).hexdigest(), 'commits': graph['commits'],
            'authorization': 'Authenticated host gh; disposable fixture credential on the emulator'}


def make_tls(folder, hosts=(HOST,)):
    conf = folder/'cert.conf'
    conf.write_text('[req]\ndistinguished_name=dn\nx509_extensions=extensions\nprompt=no\n'
                    '[dn]\nCN=Mobile Harness Forge fixture\n[extensions]\nsubjectAltName='+','.join('DNS:'+host for host in hosts)+'\n'
                    'basicConstraints=critical,CA:TRUE\nkeyUsage=critical,digitalSignature,keyEncipherment,keyCertSign\n')
    key, cert = folder/'fixture.key', folder/'fixture.pem'
    subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-days','1','-config',str(conf),
                    '-keyout',str(key),'-out',str(cert)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert, key)
    return context, cert.read_bytes()


def verify_writes(device, server, sid):
    bound = {'sessionId': sid, 'url': URL}
    review = {'kind': 'review', 'event': 'comment', 'body': REVIEW_BODY, 'comments': [INLINE]}

    def submit(head):
        return device.rpc('forgePanel/submitReview', {**bound, 'request': {**review, 'headSha': head}})

    stale = submit(SECOND)
    assert stale['ok'] is False and stale['code'] == 'stale', stale
    assert not any(row['path'] == PULL + '/reviews' for row in server.calls)
    server.review_mode = 'refuse'
    refused = submit(HEAD)
    assert refused['ok'] is False and refused['code'] == 'failed' and 'HTTP 403' in refused['message'], refused
    assert not server.reviews
    server.review_mode = 'success'
    receipt = submit(HEAD)
    assert receipt == {'ok': True, 'url': URL + '#pullrequestreview-1'}, receipt
    assert server.reviews == [REVIEW_PAYLOAD]
    server.review_mode = 'uncertain'
    count = len(server.calls)
    uncertain = submit(HEAD)
    assert uncertain['ok'] is False and uncertain['code'] == 'unknown', uncertain
    assert server.reviews == [REVIEW_PAYLOAD, REVIEW_PAYLOAD]
    assert sum(row['path'] == PULL + '/reviews' for row in server.calls[count:]) == 1

    reviewer = {'kind': 'user', 'login': 'fixture-reviewer'}
    device.rpc('forgePanel/requestReviews', {**bound, 'reviewers': [reviewer]})
    assert server.requested_reviews == [
        {'input': {'pullRequestId': 'PR_fixture', 'union': True, 'userIds': ['U_fixture']}}
    ]
    merge = {**bound, 'method': 'squash'}
    try:
        device.rpc('forgePanel/merge', {**merge, 'headSha': SECOND})
    except RuntimeError as error:
        assert str(error) == 'forgePanel/merge: forgePanel/stale-head', error
    else:
        raise AssertionError('The stale merge was not rejected')
    assert not server.merged
    device.stop()
    device.start()
    ready_ms = device.ready('normal')
    device.rpc('forgePanel/merge', {**merge, 'headSha': HEAD})
    assert server.merged
    merge_requests = [row['body'] for row in server.calls if row['path'] == PULL + '/merge']
    assert merge_requests == [{'merge_method': 'squash', 'sha': sha} for sha in (SECOND, HEAD)], merge_requests
    return {
        'reviewStaleDeniedBeforeWrite': stale['code'], 'review403Denied': refused['code'],
        'reviewReceipt': receipt, 'review503UnknownWithoutRetry': uncertain['code'],
        'reviewPayload': REVIEW_PAYLOAD, 'reviewerRequest': server.requested_reviews[0],
        'staleMergeDenied': True, 'mergeRequests': merge_requests, 'mergedAfterRestartReadyMs': ready_ms,
    }


def run(device, output, writes=False, public_read=False, port=19643):
    evidence = {}
    cases = ['package.json', 'pnpm-lock.yaml', 'cordis.patch.yml']
    original = {}
    ident = 'mh-forge-github-'+uuid.uuid4().hex[:10]
    folder = 'alpine/workspace-native/'+ident
    remote = '/data/local/tmp/'+ident
    forward = (f'tcp:{port}', 'tcp:19592')
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
        original = {path: saved_file(device,path) for path in
                    [profile+'/'+case for case in cases]+['mobile-harness-boot.json', CA_BUNDLE]}
        with tempfile.TemporaryDirectory(prefix=ident) as temp:
            context, certificate = make_tls(Path(temp))
            server = ThreadingHTTPServer(('127.0.0.1',0), PublicPullFixture if public_read else GitHubFixture)
            server.socket = context.wrap_socket(server.socket, server_side=True)
            server.calls = []
            server.reviews = []
            server.requested_reviews = []
            server.merged = False
            server.review_mode = 'success'
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
            if public_read:
                evidence['publicRead'] = verify_public_read(device, server, sid)
                return
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
            if writes:
                evidence['writes'] = verify_writes(device, server, sid)
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
                        if body is None:
                            device.app('rm -f '+path)
                        else:
                            lsp['restore_bytes'](device,path,body,remote+'-restore-'+str(i))
                    device.start()
                    evidence['restoredReadyMs']=device.ready('normal')
                    assert all(saved_file(device,path)==body for path,body in original.items())
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
    parser.add_argument('--port', type=int, default=19643)
    scenario = parser.add_mutually_exclusive_group()
    scenario.add_argument('--writes', action='store_true', help='Exercise review, review requests and merge against the isolated fixture')
    scenario.add_argument('--public-read', action='store_true', help='Read one public pull request through an allowlisted authenticated desktop gateway')
    args=parser.parse_args()
    run(support['Emulator'](args.target,args.port),args.output,args.writes,args.public_read,args.port)
