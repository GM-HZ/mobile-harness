"""Exercise repeated provider HTTP context-overflow recovery in the shipped Phone Host."""
import argparse
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import runpy
import threading
import uuid

flow = runpy.run_path(str(Path(__file__).with_name('emulator-compaction.py')))
agent, support = flow['agent'], flow['support']
lsp = runpy.run_path(str(Path(__file__).with_name('emulator-lsp-lifecycle.py')))
PATCH = 'alpine/native-benchmark-home/cordis.patch.yml'
REF = 'DEEPSEEK_API_KEY'
KEY = 'owned-context-overflow-fixture'


class MessagesFixture(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def send_body(self, status, body, content_type='application/json'):
        self.send_response(status)
        self.send_header('Content-Type',content_type)
        self.send_header('Content-Length',str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_text(self, text):
        events = [
            {'type':'message_start','message':{'id':'msg_fixture','model':'deepseek-flash',
                                               'usage':{'input_tokens':3500,'output_tokens':0}}},
            {'type':'content_block_start','index':0,'content_block':{'type':'text','text':''}},
            {'type':'content_block_delta','index':0,'delta':{'type':'text_delta','text':text}},
            {'type':'content_block_stop','index':0},
            {'type':'message_delta','delta':{'stop_reason':'end_turn'},'usage':{'output_tokens':32}},
            {'type':'message_stop'},
        ]
        body = ''.join('event: '+row['type']+'\ndata: '+json.dumps(row)+'\n\n' for row in events)
        self.send_body(200,body.encode(),'text/event-stream')

    def do_GET(self):
        if self.path.endswith('/models'):
            self.send_body(200,b'{"object":"list","data":[{"id":"deepseek-flash","object":"model"}]}')
        else:
            self.send_body(404,b'{}')

    def do_POST(self):
        if (not self.path.endswith('/messages')
                or KEY not in (self.headers.get('x-api-key'),self.headers.get('Authorization','').removeprefix('Bearer '))):
            self.send_body(401,b'{"error":{"message":"Fixture credentials or route rejected"}}')
            return
        message = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        current = json.dumps(message['messages'][-1],ensure_ascii=False)
        history = json.dumps(message['messages'],ensure_ascii=False)
        case = re.search(r'(SEED|TRIGGER)-MH-([12])',current)
        marker = self.server.marker
        record = {'path':self.path,'messageCount':len(message['messages']),'historyBytes':len(history.encode()),
                  'staleArchivePresent': 'DISCARD-FIXTURE-ROW' in history}
        if 'Write concise English engineering prose' in current:
            record.update(action='summary',status=200)
            self.send_text('Pending owned marker '+marker+'. The preceding archive was completed.')
        elif case and case[1]=='TRIGGER':
            step = int(case[2])
            if step not in self.server.faulted:
                self.server.faulted.add(step)
                record.update(action='overflow',step=step,status=400)
                self.send_body(400,json.dumps({'type':'error','error':self.server.overflow_error}).encode())
            else:
                record.update(action='retry',step=step,status=200,checkpointPresent='Pending owned marker '+marker in history)
                self.send_text(marker if record['checkpointPresent'] else 'MISSING-CHECKPOINT')
        elif 'VERIFY-MH-RESTART' in current:
            record.update(action='reopen',status=200,checkpointPresent='Pending owned marker '+marker in history)
            self.send_text(marker if record['checkpointPresent'] else 'MISSING-CHECKPOINT')
        else:
            record.update(action='seed' if case else 'other', status=200)
            self.send_text('Acknowledged')
        self.server.calls.append(record)


def run(device, output, overflow_error):
    nonce = 'mh-overflow-'+uuid.uuid4().hex[:10]
    target = '/data/local/tmp/'+nonce
    folder = 'alpine/workspace-native/'+nonce
    bridge = ('tcp:19643','tcp:19592')
    reverse = None
    patch_installed = False
    credential_installed = False
    workspace = None
    sid = None
    evidence = {'replayedError': overflow_error}
    server = ThreadingHTTPServer(('127.0.0.1',0),MessagesFixture)
    server.calls, server.faulted = [], set()
    server.overflow_error = overflow_error
    server.marker = 'OWNED_'+uuid.uuid4().hex.upper()
    threading.Thread(target=server.serve_forever,daemon=True).start()
    assert 'Forwardport result:OK' in device.hdc('fport', *bridge)
    auth = {'refs':[REF]}
    try:
        device.ready('normal')
        assert device.app('test ! -e '+PATCH+' && printf EMPTY')=='EMPTY'
        assert not device.rpc('credentials/describe',auth)[REF]['configured']
        candidate = ('tcp:19773',f'tcp:{server.server_port}')
        assert 'Forwardport result:OK' in device.hdc('rport',*candidate)
        reverse = candidate
        device.stop()
        patch = '- id: llm-deepseek\n  config:\n    baseURL: http://127.0.0.1:19773/anthropic\n'
        patch_installed = True
        lsp['restore_bytes'](device,PATCH,patch.encode(),target+'-routing')
        device.app('mkdir '+folder)
        device.start()
        device.ready('normal')
        device.rpc('credentials/set',{'ref':REF,'value':KEY})
        credential_installed = True
        workspace = device.rpc('workspace/create',{'request':{'path':support['WORKSPACE']+'/'+nonce}})['workspace']['workspaceId']
        sid = device.rpc('session/create',{'request':{'workspaceId':workspace}})['sessionId']
        device.rpc('session/selectModel',{'request':{'sessionId':sid,'provider':'deepseek-official',
                   'model':'deepseek-flash','reasoningEffort':'off'}})
        evidence['recoveries']=[]
        for index in (1,2):
            discard = '\n'.join(f'DISCARD-FIXTURE-ROW {i}: '+hashlib.sha256(str(i).encode()).hexdigest() for i in range(180))
            agent['prompt'](device,sid,f'SEED-MH-{index} owned marker {server.marker}\n'+discard,timeout=35)
            before = support['events'](device,sid)
            _, _, after = agent['prompt'](device,sid,f'TRIGGER-MH-{index} recall the owned marker',timeout=45)
            recent = [row for row in after if row['seq']>before[-1]['seq']]
            assert agent['assistant_texts'](recent).strip()==server.marker,recent[-2:]
            kinds = [row['type'] for row in recent if row['type'].startswith('compaction/')]
            assert kinds==['compaction/start','compaction/summary','compaction/end'],kinds
            current = {row['seq']:row for row in after}
            assert all(current[row['seq']]==row for row in before)
            assert sum(row['type']=='turn/start' for row in recent)==1
            sample = [row for row in server.calls if row.get('step')==index]
            assert [row['action'] for row in sample]==['overflow','retry'],sample
            assert sample[0]['staleArchivePresent'] and sample[1]['checkpointPresent'],sample
            assert sample[1]['historyBytes']<sample[0]['historyBytes'],sample
            evidence['recoveries'].append({'overflow':sample[0],'retry':sample[1],
                                           'compactionEvents':kinds,'oldJournalUnchanged':True})
        assert sum(row['action']=='summary' for row in server.calls)==2
        device.stop()
        device.start()
        device.ready('normal')
        before = support['events'](device,sid)
        _, _, after = agent['prompt'](device,sid,'VERIFY-MH-RESTART',timeout=35)
        assert agent['assistant_texts']([row for row in after if row['seq']>before[-1]['seq']]).strip()==server.marker
        assert sum(row['type']=='compaction/summary' for row in after)==2
        evidence['reopenedAtLatestCheckpoint']=True
    finally:
        try:
            try:
                if sid:
                    device.rpc('session/cancel',{'request':{'sessionId':sid}})
                    device.rpc('workspace/archiveSession',{'request':{'sessionId':sid}})
                if workspace:
                    device.rpc('workspace/delete',{'request':{'workspaceId':workspace}})
            finally:
                if credential_installed:
                    device.rpc('credentials/unset',{'ref':REF})
                    assert not device.rpc('credentials/describe',auth)[REF]['configured']
                if patch_installed:
                    device.stop()
                    device.app('rm -f '+PATCH+'; rm -rf '+folder)
                    device.start()
                    evidence['restoredReadyMs']=device.ready('normal')
                    assert device.app('test ! -e '+PATCH+' && printf EMPTY')=='EMPTY'
                    evidence['fixtureConfigRemoved']=True
        finally:
            if reverse:
                device.hdc('fport','rm',*reverse)
            device.hdc('fport','rm',*bridge)
            server.shutdown()
            server.server_close()
            evidence['requests']=server.calls
            output.write_text(json.dumps(evidence,indent=2)+'\n')


if __name__=='__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('target')
    parser.add_argument('output',type=Path)
    parser.add_argument('--provider-error-report',type=Path,help='Replay a captured public provider HTTP 400 envelope')
    args = parser.parse_args()
    error = {'message':'Maximum context length exceeded.',
             'type':'invalid_request_error','code':'context_length_exceeded'}
    if args.provider_error_report:
        report = json.loads(args.provider_error_report.read_text())
        assert report['httpStatus']==400 and report['explicitWindowRejection']
        error = {key: report['error'][key] for key in ('type','message')}
        error['message'] = re.sub(r' \(request_id: [^)]+\)$','',error['message'])
    run(support['Emulator'](args.target,19643),args.output,error)
